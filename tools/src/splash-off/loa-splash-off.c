/*
 * loa-splash-off: cleanly switch off the bootloader's continuous-splash display
 * before the compositor starts, so its first commit is a full panel enable
 * instead of a first-frame "DMS" (which the Qualcomm DSI driver rejects,
 * leaving the connector without backlight control).
 * Atomic: DSI connector CRTC_ID=0, its CRTC ACTIVE=0 MODE_ID=0, planes detached.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>

static int fd;
static uint32_t prop(uint32_t obj, uint32_t type, const char *name, uint64_t *val) {
	struct drm_mode_obj_get_properties op = { .obj_id = obj, .obj_type = type };
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0;
	uint32_t ids[256]; uint64_t vals[256]; if (op.count_props > 256) op.count_props = 256;
	op.props_ptr = (uintptr_t)ids; op.prop_values_ptr = (uintptr_t)vals;
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0;
	for (uint32_t i = 0; i < op.count_props; i++) {
		struct drm_mode_get_property gp = { .prop_id = ids[i] };
		if (!ioctl(fd, DRM_IOCTL_MODE_GETPROPERTY, &gp) && !strcmp(gp.name, name)) { if (val) *val = vals[i]; return ids[i]; }
	}
	return 0;
}
static uint32_t objs[64], counts[64], props[128]; static uint64_t vals[128]; static int nobj, nprop;
static void add(uint32_t obj, uint32_t type, const char *name, uint64_t v) {
	uint32_t p = prop(obj, type, name, NULL); if (!p) { fprintf(stderr, "no prop %s on %u\n", name, obj); return; }
	if (!nobj || objs[nobj - 1] != obj) { objs[nobj] = obj; counts[nobj++] = 0; }
	counts[nobj - 1]++; props[nprop] = p; vals[nprop++] = v;
}
int main(void) {
	fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	if (fd < 0 || ioctl(fd, DRM_IOCTL_SET_MASTER, 0)) { perror("card0/master"); return 1; }
	struct drm_set_client_cap cap = { DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1 }; ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap);
	cap.capability = DRM_CLIENT_CAP_ATOMIC; if (ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap)) { perror("atomic"); return 1; }
	struct drm_mode_card_res res = {0}; uint32_t conns[32], crtcs[32];
	ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res);
	res.count_fbs = res.count_encoders = 0; res.connector_id_ptr = (uintptr_t)conns; res.crtc_id_ptr = (uintptr_t)crtcs;
	if (res.count_connectors > 32) res.count_connectors = 32; if (res.count_crtcs > 32) res.count_crtcs = 32;
	if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) { perror("res"); return 1; }
	uint32_t conn = 0; uint64_t crtc = 0;
	for (uint32_t i = 0; i < res.count_connectors && !conn; i++) {
		struct drm_mode_get_connector c = { .connector_id = conns[i] };
		if (!ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) && c.connector_type == DRM_MODE_CONNECTOR_DSI) { conn = conns[i]; prop(conn, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID", &crtc); }
	}
	printf("DSI connector %u on crtc %llu\n", conn, (unsigned long long)crtc);
	if (!conn || !crtc) { printf("nothing to switch off\n"); return 0; }
	add(conn, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID", 0);
	uint32_t planes[64]; struct drm_mode_get_plane_res pr = { .plane_id_ptr = (uintptr_t)planes, .count_planes = 64 };
	ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &pr);
	for (uint32_t i = 0; i < pr.count_planes; i++) {
		uint64_t pc = 0; prop(planes[i], DRM_MODE_OBJECT_PLANE, "CRTC_ID", &pc);
		if (pc == crtc) { add(planes[i], DRM_MODE_OBJECT_PLANE, "FB_ID", 0); add(planes[i], DRM_MODE_OBJECT_PLANE, "CRTC_ID", 0); printf("detach plane %u\n", planes[i]); }
	}
	add((uint32_t)crtc, DRM_MODE_OBJECT_CRTC, "ACTIVE", 0);
	add((uint32_t)crtc, DRM_MODE_OBJECT_CRTC, "MODE_ID", 0);
	struct drm_mode_atomic at = { .flags = DRM_MODE_ATOMIC_ALLOW_MODESET, .count_objs = nobj, .objs_ptr = (uintptr_t)objs,
		.count_props_ptr = (uintptr_t)counts, .props_ptr = (uintptr_t)props, .prop_values_ptr = (uintptr_t)vals };
	int r = ioctl(fd, DRM_IOCTL_MODE_ATOMIC, &at);
	printf("splash off commit: %s\n", r ? strerror(errno) : "ok");
	ioctl(fd, DRM_IOCTL_DROP_MASTER, 0);
	return r ? 1 : 0;
}
