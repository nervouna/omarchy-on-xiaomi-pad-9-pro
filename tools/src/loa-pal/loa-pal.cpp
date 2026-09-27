// loa-pal: minimal client for the stock Qualcomm PAL service (libpalclient ->
// vendor.qti.hardware.pal.IPAL over binder), run inside /opt/loa-android.
//   loa-pal record [SECONDS]   capture PAL_DEVICE_IN_SPEAKER_MIC -> stdout (S16LE 48k stereo)
//   loa-pal play               stdin (S16LE 48k stereo) -> PAL_DEVICE_OUT_SPEAKER
// Optional last argument DEVICE_ID overrides the PAL device id (vendor enum numbering differs).
// SECONDS=0 (default) runs until stdin/stdout closes.
#include <PalApi.h>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <unistd.h>
#include <signal.h>

static volatile sig_atomic_t stop_flag;
static void on_sig(int) { stop_flag = 1; }

static void media(pal_media_config &c) {
    c.sample_rate = 48000; c.bit_width = 16; c.aud_fmt_id = PAL_AUDIO_FMT_PCM_S16_LE;
    c.ch_info.channels = 2; c.ch_info.ch_map[0] = PAL_CHMAP_CHANNEL_FL; c.ch_info.ch_map[1] = PAL_CHMAP_CHANNEL_FR;
}

int main(int argc, char **argv) {
    if (argc < 2 || (strcmp(argv[1], "record") && strcmp(argv[1], "play"))) {
        fprintf(stderr, "usage: loa-pal record [SECONDS [DEVICE_ID]] | play [DEVICE_ID]\n"); return 2;
    }
    bool rec = !strcmp(argv[1], "record");
    int secs = argc > 2 ? atoi(argv[2]) : 0;
    signal(SIGINT, on_sig); signal(SIGTERM, on_sig); signal(SIGPIPE, on_sig);

    pal_stream_attributes a; memset(&a, 0, sizeof a);
    a.type = rec ? PAL_STREAM_DEEP_BUFFER : PAL_STREAM_DEEP_BUFFER;
    a.direction = rec ? PAL_AUDIO_INPUT : PAL_AUDIO_OUTPUT;
    if (rec) media(a.in_media_config); else media(a.out_media_config);

    pal_device d; memset(&d, 0, sizeof d);
    d.id = rec ? PAL_DEVICE_IN_SPEAKER_MIC : PAL_DEVICE_OUT_SPEAKER;
    const char *dev_arg = rec ? (argc > 3 ? argv[3] : nullptr) : (argc > 2 ? argv[2] : nullptr);
    if (dev_arg) d.id = (pal_device_id_t)strtol(dev_arg, nullptr, 0);
    media(d.config);

    pal_stream_handle_t *h = nullptr;
    int r = pal_stream_open(&a, 1, &d, 0, nullptr, nullptr, 0, &h);
    if (r) { fprintf(stderr, "pal_stream_open failed %d\n", r); return 1; }
    size_t in_sz = 0, out_sz = 0;
    pal_buffer_config in_cfg{}, out_cfg{};
    in_cfg.buf_count = 4; in_cfg.buf_size = 3840; out_cfg.buf_count = 4; out_cfg.buf_size = 3840;
    pal_stream_set_buffer_size(h, &in_cfg, &out_cfg);  // this libpalclient dereferences both
    (void)in_sz; (void)out_sz;
    if ((r = pal_stream_start(h))) { fprintf(stderr, "pal_stream_start failed %d\n", r); pal_stream_close(h); return 1; }
    fprintf(stderr, "loa-pal: %s started\n", rec ? "record" : "play");

    static uint8_t buf[3840];
    time_t end = secs > 0 ? time(nullptr) + secs : 0;
    while (!stop_flag && (!end || time(nullptr) < end)) {
        pal_buffer b; memset(&b, 0, sizeof b); b.buffer = buf; b.size = sizeof buf;
        if (rec) {
            ssize_t n = pal_stream_read(h, &b);
            if (n <= 0) { fprintf(stderr, "pal_stream_read %zd\n", n); break; }
            if (write(1, buf, n) != n) break;
        } else {
            ssize_t got = 0;
            while (got < (ssize_t)sizeof buf) { ssize_t n = read(0, buf + got, sizeof buf - got); if (n <= 0) { stop_flag = 1; break; } got += n; }
            if (got <= 0) break;
            b.size = got;
            if (pal_stream_write(h, &b) < 0) { fprintf(stderr, "pal_stream_write failed\n"); break; }
        }
    }
    pal_stream_stop(h); pal_stream_close(h);
    fprintf(stderr, "loa-pal: done\n");
    return 0;
}
