// loa-bthci: bridge the stock Qualcomm Bluetooth HAL (android.hardware.bluetooth
// IBluetoothHci/default, which powers the WCN7750 and downloads its firmware) to
// Linux BlueZ. Runs inside /opt/loa-android. After initializationComplete it
// opens a PTY, writes the slave path to PATHFILE and relays H4 frames:
//   PTY (hci_uart H4 ldisc via `btattach -P h4`) <-> IBluetoothHci
// The GKI kernel has no hci_vhci, so the PTY + hci_uart is the way in.
//   loa-bthci PATHFILE
#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>
#include <errno.h>
#include <fcntl.h>
#include <mutex>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>
#include <condition_variable>
#include <vector>

// LLNDK, not in the NDK headers: declared here, resolved from the device's libbinder_ndk.so.
extern "C" {
AIBinder *AServiceManager_waitForService(const char *instance);
void AIBinder_markVintfStability(AIBinder *binder);
void ABinderProcess_setThreadPoolMaxThreadCount(uint32_t numThreads);
void ABinderProcess_startThreadPool(void);
}

static const char *kHci = "android.hardware.bluetooth.IBluetoothHci";
static const char *kCb = "android.hardware.bluetooth.IBluetoothHciCallbacks";
static const char *kCbHash = "f0eb2eb6d3b970cef8fb1b6e22c4ec39a4da5119";  // V1, from the vendor stub
// Stable AIDL V1 declares both interfaces alphabetically.
enum { HCI_CLOSE = FIRST_CALL_TRANSACTION, HCI_INITIALIZE, HCI_SEND_ACL, HCI_SEND_CMD, HCI_SEND_ISO, HCI_SEND_SCO };
enum { CB_ACL = FIRST_CALL_TRANSACTION, CB_EVENT, CB_INIT_COMPLETE, CB_ISO, CB_SCO };
static const transaction_code_t kGetVersion = FIRST_CALL_TRANSACTION + 16777214;
static const transaction_code_t kGetHash = FIRST_CALL_TRANSACTION + 16777213;
enum { H4_CMD = 1, H4_ACL = 2, H4_SCO = 3, H4_EVT = 4, H4_ISO = 5 };

static int g_master = -1;
static std::mutex g_write_mu, g_init_mu;
static std::condition_variable g_init_cv;
static int g_init_status = -1;
static bool g_init_done = false;

static bool alloc_bytes(void *data, int32_t len, int8_t **out) {
    auto *v = static_cast<std::vector<int8_t> *>(data);
    if (len < 0) return false;
    v->resize(len); *out = v->data();
    return true;
}

static void to_host(uint8_t type, const std::vector<int8_t> &p) {
    std::lock_guard<std::mutex> l(g_write_mu);
    if (g_master < 0) return;
    std::vector<uint8_t> buf(1 + p.size());
    buf[0] = type; memcpy(buf.data() + 1, p.data(), p.size());
    size_t off = 0;
    while (off < buf.size()) {
        ssize_t n = write(g_master, buf.data() + off, buf.size() - off);
        if (n < 0) { if (errno == EINTR) continue; perror("loa-bthci: pty write"); return; }
        off += n;
    }
}

static void *cb_create(void *) { return nullptr; }
static void cb_destroy(void *) {}
static binder_status_t cb_transact(AIBinder *, transaction_code_t code, const AParcel *in, AParcel *out) {
    std::vector<int8_t> data;
    switch (code) {
    case CB_ACL: case CB_EVENT: case CB_ISO: case CB_SCO: {
        binder_status_t s = AParcel_readByteArray(in, &data, alloc_bytes);
        if (s != STATUS_OK) return s;
        to_host(code == CB_ACL ? H4_ACL : code == CB_EVENT ? H4_EVT : code == CB_ISO ? H4_ISO : H4_SCO, data);
        break;
    }
    case CB_INIT_COMPLETE: {
        int32_t st = -1;
        binder_status_t s = AParcel_readInt32(in, &st);
        if (s != STATUS_OK) return s;
        fprintf(stderr, "loa-bthci: initializationComplete status=%d\n", st);
        { std::lock_guard<std::mutex> l(g_init_mu); g_init_status = st; g_init_done = true; }
        g_init_cv.notify_all();
        break;
    }
    case kGetVersion: {
        AStatus *ok = AStatus_newOk(); AParcel_writeStatusHeader(out, ok); AStatus_delete(ok);
        return AParcel_writeInt32(out, 1);
    }
    case kGetHash: {
        AStatus *ok = AStatus_newOk(); AParcel_writeStatusHeader(out, ok); AStatus_delete(ok);
        return AParcel_writeString(out, kCbHash, strlen(kCbHash));
    }
    default:
        return STATUS_UNKNOWN_TRANSACTION;
    }
    AStatus *ok = AStatus_newOk();
    binder_status_t s = AParcel_writeStatusHeader(out, ok);
    AStatus_delete(ok);
    return s;
}

static AIBinder *g_hci;
static bool call(transaction_code_t code, const void *data, int32_t len, AIBinder *binder_arg = nullptr) {
    AParcel *in = nullptr, *out = nullptr;
    if (AIBinder_prepareTransaction(g_hci, &in) != STATUS_OK) return false;
    binder_status_t s = binder_arg ? AParcel_writeStrongBinder(in, binder_arg)
                                   : AParcel_writeByteArray(in, (const int8_t *)data, len);
    if (s == STATUS_OK) s = AIBinder_transact(g_hci, code, &in, &out, 0);
    if (s != STATUS_OK) { fprintf(stderr, "loa-bthci: transact %u failed: %d\n", code, s); return false; }
    AStatus *st = nullptr;
    s = AParcel_readStatusHeader(out, &st);
    bool ok = s == STATUS_OK && st && AStatus_isOk(st);
    if (!ok) fprintf(stderr, "loa-bthci: call %u returned %s\n", code, st ? AStatus_getDescription(st) : "?");
    if (st) AStatus_delete(st);
    AParcel_delete(out);
    return ok;
}

static bool read_full(int fd, uint8_t *p, size_t n) {
    while (n) {
        ssize_t r = read(fd, p, n);
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) return false;
        p += r; n -= r;
    }
    return true;
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: loa-bthci PATHFILE\n"); return 2; }
    ABinderProcess_setThreadPoolMaxThreadCount(2);
    ABinderProcess_startThreadPool();

    std::string inst = std::string(kHci) + "/default";
    g_hci = AServiceManager_waitForService(inst.c_str());
    if (!g_hci) { fprintf(stderr, "loa-bthci: no %s\n", inst.c_str()); return 1; }
    AIBinder_Class *hci_cls = AIBinder_Class_define(kHci, cb_create, cb_destroy, cb_transact);
    if (!AIBinder_associateClass(g_hci, hci_cls)) { fprintf(stderr, "loa-bthci: associateClass failed\n"); return 1; }

    // PTY first, so no HAL callback is lost; the host side attaches after init.
    g_master = posix_openpt(O_RDWR | O_NOCTTY);
    if (g_master < 0 || grantpt(g_master) || unlockpt(g_master)) { perror("loa-bthci: pty"); return 1; }
    struct termios t; tcgetattr(g_master, &t); cfmakeraw(&t); tcsetattr(g_master, TCSANOW, &t);
    const char *slave = ptsname(g_master);
    // Hold the slave open: with no slave fd the master reads EIO before btattach attaches.
    int keep_slave = open(slave, O_RDWR | O_NOCTTY);
    if (keep_slave < 0) { perror("loa-bthci: slave"); return 1; }

    AIBinder_Class *cb_cls = AIBinder_Class_define(kCb, cb_create, cb_destroy, cb_transact);
    AIBinder *cb = AIBinder_new(cb_cls, nullptr);
    AIBinder_markVintfStability(cb);
    fprintf(stderr, "loa-bthci: initialize\n");
    if (!call(HCI_INITIALIZE, nullptr, 0, cb)) return 1;
    {
        std::unique_lock<std::mutex> l(g_init_mu);
        if (!g_init_cv.wait_for(l, std::chrono::seconds(30), [] { return g_init_done; })) {
            fprintf(stderr, "loa-bthci: initialization timed out\n"); return 1;
        }
    }
    if (g_init_status != 0) return 1;

    FILE *f = fopen(argv[1], "w");
    if (!f) { perror("loa-bthci: PATHFILE"); return 1; }
    fprintf(f, "%s\n", slave); fclose(f);
    fprintf(stderr, "loa-bthci: ready on %s\n", slave);

    // Host -> controller: H4 frames from hci_uart.
    std::vector<uint8_t> buf(4 + 65536);
    for (;;) {
        uint8_t type;
        if (!read_full(g_master, &type, 1)) break;
        size_t hdr, len;
        switch (type) {
        case H4_CMD: hdr = 3; break;
        case H4_ACL: case H4_ISO: hdr = 4; break;
        case H4_SCO: hdr = 3; break;
        default: fprintf(stderr, "loa-bthci: bad H4 type 0x%02x\n", type); continue;
        }
        if (!read_full(g_master, buf.data(), hdr)) break;
        if (type == H4_CMD || type == H4_SCO) len = buf[2];
        else if (type == H4_ACL) len = buf[2] | (buf[3] << 8);
        else len = (buf[2] | (buf[3] << 8)) & 0x3fff;
        if (!read_full(g_master, buf.data() + hdr, len)) break;
        transaction_code_t code = type == H4_CMD ? HCI_SEND_CMD : type == H4_ACL ? HCI_SEND_ACL
                                : type == H4_SCO ? HCI_SEND_SCO : HCI_SEND_ISO;
        call(code, buf.data(), hdr + len);
    }
    fprintf(stderr, "loa-bthci: pty closed, shutting down\n");
    call(HCI_CLOSE, nullptr, 0);
    return 0;
}
