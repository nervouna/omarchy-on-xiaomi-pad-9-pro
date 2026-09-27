/*
 * loa-kmstest: minimal libdrm-free atomic KMS test for the shuntian DSI panel.
 * Static musl build runs both on rooted Android (composer stopped) and native.
 *
 * usage: loa-kmstest [-d /dev/dri/card0] [-r HZ] [-l single|split] [-t SECONDS]
 *                    [-p PLANE_ID[,PLANE_ID]] [-f]
 *   -l single : one plane covering the full 3200-wide CRTC
 *   -l split  : two planes, each covering one 1600-wide mixer half (like HWC)
 *   -f        : flip between two buffers at ~10 Hz (moving marker)
 * Pattern: 8 vertical color bars, 64px checker, white border, numbered rows.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <drm/drm_fourcc.h>

#define MAXP 64
static int fd;
static volatile sig_atomic_t stop;
static void on_sig(int s) { (void)s; stop = 1; }
static int64_t ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000LL + t.tv_nsec / 1000000; }
static int xioctl(unsigned long req, void *arg) { int r; do r = ioctl(fd, req, arg); while (r < 0 && (errno == EINTR || errno == EAGAIN)); return r; }
#define DIE(...) do { fprintf(stderr, __VA_ARGS__); fprintf(stderr, " (errno %d %s)\n", errno, strerror(errno)); exit(1); } while (0)

static uint32_t prop_id(uint32_t obj, uint32_t type, const char *name, uint64_t *val) {
	struct drm_mode_obj_get_properties op = { .obj_id = obj, .obj_type = type };
	if (xioctl(DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0;
	uint32_t ids[256]; uint64_t vals[256];
	if (op.count_props > 256) op.count_props = 256;
	op.props_ptr = (uintptr_t)ids; op.prop_values_ptr = (uintptr_t)vals;
	if (xioctl(DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0;
	for (uint32_t i = 0; i < op.count_props; i++) {
		struct drm_mode_get_property gp = { .prop_id = ids[i] };
		if (xioctl(DRM_IOCTL_MODE_GETPROPERTY, &gp)) continue;
		if (!strcmp(gp.name, name)) { if (val) *val = vals[i]; return ids[i]; }
	}
	return 0;
}

struct areq { uint32_t objs[64], counts[64], props[256]; uint64_t vals[256]; int nobj, nprop; };
static void aadd(struct areq *a, uint32_t obj, uint32_t type, const char *name, uint64_t v) {
	uint32_t p = prop_id(obj, type, name, NULL);
	if (!p) DIE("property %s missing on %u", name, obj);
	if (!a->nobj || a->objs[a->nobj - 1] != obj) { a->objs[a->nobj] = obj; a->counts[a->nobj++] = 0; }
	a->counts[a->nobj - 1]++; a->props[a->nprop] = p; a->vals[a->nprop++] = v;
}
static int acommit(struct areq *a, uint32_t flags, void *ud) {
	struct drm_mode_atomic at = { .flags = flags, .count_objs = a->nobj, .objs_ptr = (uintptr_t)a->objs,
		.count_props_ptr = (uintptr_t)a->counts, .props_ptr = (uintptr_t)a->props,
		.prop_values_ptr = (uintptr_t)a->vals, .user_data = (uintptr_t)ud };
	int r = ioctl(fd, DRM_IOCTL_MODE_ATOMIC, &at);
	return r ? -errno : 0;
}

struct bo { uint32_t handle, pitch, fb; uint64_t size; uint32_t *map; };
static const uint32_t bars[8] = { 0xffffff, 0xffff00, 0x00ffff, 0x00ff00, 0xff00ff, 0xff0000, 0x0000ff, 0x404040 };
static void draw(struct bo *b, int W, int H, int variant) {
	for (int y = 0; y < H; y++) {
		uint32_t *row = (uint32_t *)((uint8_t *)b->map + (size_t)y * b->pitch);
		for (int x = 0; x < W; x++) {
			uint32_t c = bars[x * 8 / W];
			if (((x >> 6) ^ (y >> 6)) & 1) c = (c >> 1) & 0x7f7f7f;
			if (x < 8 || y < 8 || x >= W - 8 || y >= H - 8) c = 0xffffff;
			/* horizontal black line every 256 rows: easy to count how far output reaches */
			if (y % 256 < 4) c = 0x000000;
			/* moving red marker block for flip variant */
			int mx = (variant * 97) % (W - 200);
			if (x >= mx && x < mx + 200 && y >= H / 2 - 100 && y < H / 2 + 100) c = variant & 1 ? 0xff0000 : 0x00ff00;
			row[x] = c | 0xff000000u;
		}
	}
}
static void mkbo(struct bo *b, int W, int H) {
	struct drm_mode_create_dumb c = { .width = W, .height = H, .bpp = 32 };
	if (xioctl(DRM_IOCTL_MODE_CREATE_DUMB, &c)) DIE("create_dumb");
	b->handle = c.handle; b->pitch = c.pitch; b->size = c.size;
	struct drm_mode_map_dumb m = { .handle = c.handle };
	if (xioctl(DRM_IOCTL_MODE_MAP_DUMB, &m)) DIE("map_dumb");
	b->map = mmap(0, c.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, m.offset);
	if (b->map == MAP_FAILED) DIE("mmap");
	struct drm_mode_fb_cmd2 f = { .width = W, .height = H, .pixel_format = DRM_FORMAT_XRGB8888 };
	f.handles[0] = b->handle; f.pitches[0] = b->pitch;
	if (xioctl(DRM_IOCTL_MODE_ADDFB2, &f)) DIE("addfb2");
	b->fb = f.fb_id;
	printf("BO fb=%u pitch=%u size=%llu\n", b->fb, b->pitch, (unsigned long long)b->size);
}

int main(int argc, char **argv) {
	const char *dev = "/dev/dri/card0", *layout = "split", *plist = NULL;
	int hz = 120, secs = 15, doflip = 0, o;
	while ((o = getopt(argc, argv, "d:r:l:t:p:f")) != -1) switch (o) {
		case 'd': dev = optarg; break; case 'r': hz = atoi(optarg); break;
		case 'l': layout = optarg; break; case 't': secs = atoi(optarg); break;
		case 'p': plist = optarg; break; case 'f': doflip = 1; break;
		default: fprintf(stderr, "bad args\n"); return 2; }
	int split = !strcmp(layout, "split");
	setvbuf(stdout, NULL, _IOLBF, 0);
	signal(SIGINT, on_sig); signal(SIGTERM, on_sig);
	fd = open(dev, O_RDWR | O_CLOEXEC);
	if (fd < 0) DIE("open %s", dev);
	if (xioctl(DRM_IOCTL_SET_MASTER, 0)) DIE("set_master (is the compositor stopped?)");
	struct drm_set_client_cap cap = { DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1 };
	if (xioctl(DRM_IOCTL_SET_CLIENT_CAP, &cap)) DIE("cap universal");
	cap.capability = DRM_CLIENT_CAP_ATOMIC;
	if (xioctl(DRM_IOCTL_SET_CLIENT_CAP, &cap)) DIE("cap atomic");

	struct drm_mode_card_res res = {0};
	if (xioctl(DRM_IOCTL_MODE_GETRESOURCES, &res)) DIE("getresources");
	uint32_t crtcs[32], conns[32], encs[32], fbs[64];
	res.count_fbs = res.count_fbs > 64 ? 64 : res.count_fbs;
	res.crtc_id_ptr = (uintptr_t)crtcs; res.connector_id_ptr = (uintptr_t)conns; res.encoder_id_ptr = (uintptr_t)encs; res.fb_id_ptr = (uintptr_t)fbs;
	if (xioctl(DRM_IOCTL_MODE_GETRESOURCES, &res)) DIE("getresources2");

	uint32_t conn_id = 0, crtc_id = 0; int crtc_idx = -1;
	struct drm_mode_modeinfo modes[64], mode; int found = 0;
	for (uint32_t i = 0; i < res.count_connectors && !conn_id; i++) {
		struct drm_mode_get_connector c = { .connector_id = conns[i] };
		if (xioctl(DRM_IOCTL_MODE_GETCONNECTOR, &c)) continue;
		if (c.connector_type != DRM_MODE_CONNECTOR_DSI || c.connection != 1) continue;
		uint32_t ce[16]; uint32_t np = c.count_props; uint32_t pp[256]; uint64_t pv[256];
		if (c.count_modes > 64) c.count_modes = 64; if (c.count_encoders > 16) c.count_encoders = 16; if (np > 256) c.count_props = 256;
		c.modes_ptr = (uintptr_t)modes; c.encoders_ptr = (uintptr_t)ce; c.props_ptr = (uintptr_t)pp; c.prop_values_ptr = (uintptr_t)pv;
		if (xioctl(DRM_IOCTL_MODE_GETCONNECTOR, &c)) continue;
		conn_id = c.connector_id;
		for (uint32_t m = 0; m < c.count_modes; m++) {
			printf("MODE[%u] %s %ux%u clock=%u htot=%u vtot=%u vrefresh=%u\n", m, modes[m].name, modes[m].hdisplay, modes[m].vdisplay, modes[m].clock, modes[m].htotal, modes[m].vtotal, modes[m].vrefresh);
			if (!found && modes[m].vrefresh == (uint32_t)hz) { mode = modes[m]; found = 1; }
		}
		for (uint32_t e = 0; e < c.count_encoders && crtc_idx < 0; e++) {
			struct drm_mode_get_encoder enc = { .encoder_id = ce[e] };
			if (xioctl(DRM_IOCTL_MODE_GETENCODER, &enc)) continue;
			for (uint32_t k = 0; k < res.count_crtcs; k++) if (enc.possible_crtcs & (1u << k)) { crtc_idx = k; crtc_id = crtcs[k]; break; }
		}
	}
	if (!conn_id || crtc_idx < 0 || !found) DIE("no DSI connector/crtc/mode %dHz", hz);
	int W = mode.hdisplay, H = mode.vdisplay;
	printf("USING conn=%u crtc=%u mode=%s %dx%d@%u clock=%u\n", conn_id, crtc_id, mode.name, W, H, mode.vrefresh, mode.clock);

	/* planes */
	uint32_t plane_ids[MAXP]; struct drm_mode_get_plane_res pr = { .plane_id_ptr = (uintptr_t)plane_ids, .count_planes = MAXP };
	if (xioctl(DRM_IOCTL_MODE_GETPLANERESOURCES, &pr)) DIE("planeres");
	uint32_t use[2] = {0}; int nuse = 0;
	if (plist) { char *e; use[0] = strtoul(plist, &e, 10); nuse = 1; if (*e == ',') { use[1] = strtoul(e + 1, 0, 10); nuse = 2; } }
	for (uint32_t i = 0; i < pr.count_planes; i++) {
		uint32_t fmts[128]; struct drm_mode_get_plane gp = { .plane_id = plane_ids[i], .format_type_ptr = (uintptr_t)fmts, .count_format_types = 128 };
		if (xioctl(DRM_IOCTL_MODE_GETPLANE, &gp)) continue;
		int xr = 0; for (uint32_t f = 0; f < gp.count_format_types && f < 128; f++) xr |= fmts[f] == DRM_FORMAT_XRGB8888;
		uint64_t type = 99; prop_id(gp.plane_id, DRM_MODE_OBJECT_PLANE, "type", &type);
		uint64_t mw = 0; prop_id(gp.plane_id, DRM_MODE_OBJECT_PLANE, "max_width", &mw) || 1;
		printf("PLANE %u type=%llu crtcs=0x%x xrgb=%d cur_crtc=%u fb=%u\n", gp.plane_id, (unsigned long long)type, gp.possible_crtcs, xr, gp.crtc_id, gp.fb_id);
		if (!plist && xr && (gp.possible_crtcs & (1u << crtc_idx)) && nuse < (split ? 2 : 1) && type != 2) use[nuse++] = gp.plane_id;
	}
	if (nuse < (split ? 2 : 1)) DIE("not enough planes");
	printf("LAYOUT %s planes=%u,%u\n", split ? "split" : "single", use[0], split ? use[1] : 0);

	struct bo b[2]; mkbo(&b[0], W, H); draw(&b[0], W, H, 0);
	if (doflip) { mkbo(&b[1], W, H); draw(&b[1], W, H, 1); }

	struct drm_mode_create_blob cb = { .data = (uintptr_t)&mode, .length = sizeof mode };
	if (xioctl(DRM_IOCTL_MODE_CREATEPROPBLOB, &cb)) DIE("blob");

	/* disable every other plane on our crtc, then set ours */
	struct areq a = {0};
	aadd(&a, crtc_id, DRM_MODE_OBJECT_CRTC, "MODE_ID", cb.blob_id);
	aadd(&a, crtc_id, DRM_MODE_OBJECT_CRTC, "ACTIVE", 1);
	aadd(&a, conn_id, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID", crtc_id);
	for (uint32_t i = 0; i < pr.count_planes; i++) {
		uint32_t id = plane_ids[i];
		if (id == use[0] || (split && id == use[1])) continue;
		uint64_t cur = 0; prop_id(id, DRM_MODE_OBJECT_PLANE, "CRTC_ID", &cur);
		if (!cur) continue;
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "FB_ID", 0);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_ID", 0);
	}
	int n = split ? 2 : 1;
	for (int k = 0; k < n; k++) {
		int x0 = split ? k * W / 2 : 0, w = split ? W / 2 : W;
		uint32_t id = use[k];
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "FB_ID", b[0].fb);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_ID", crtc_id);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "SRC_X", (uint64_t)x0 << 16);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "SRC_Y", 0);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "SRC_W", (uint64_t)w << 16);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "SRC_H", (uint64_t)H << 16);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_X", x0);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_Y", 0);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_W", w);
		aadd(&a, id, DRM_MODE_OBJECT_PLANE, "CRTC_H", H);
	}
	int r = acommit(&a, DRM_MODE_ATOMIC_ALLOW_MODESET | DRM_MODE_ATOMIC_TEST_ONLY, 0);
	printf("TEST_ONLY ret=%d\n", r);
	if (r) return 1;
	r = acommit(&a, DRM_MODE_ATOMIC_ALLOW_MODESET, 0);
	printf("MODESET ret=%d t=%lld\n", r, (long long)ms());
	if (r) return 1;

	int64_t end = ms() + secs * 1000LL; int cur = 0, flips = 0;
	while (!stop && ms() < end) {
		if (doflip) {
			cur ^= 1; draw(&b[cur], W, H, flips + 2);
			struct areq f = {0};
			for (int k = 0; k < n; k++) aadd(&f, use[k], DRM_MODE_OBJECT_PLANE, "FB_ID", b[cur].fb);
			r = acommit(&f, DRM_MODE_PAGE_FLIP_EVENT, 0);
			if (r) { printf("FLIP %d ret=%d\n", flips, r); break; }
			struct pollfd p = { fd, POLLIN }; char evb[256];
			if (poll(&p, 1, 1000) > 0) (void)!read(fd, evb, sizeof evb); else printf("FLIP %d no event\n", flips);
			flips++;
			usleep(100000);
		} else usleep(200000);
	}
	printf("DONE flips=%d t=%lld\n", flips, (long long)ms());
	return 0;
}
