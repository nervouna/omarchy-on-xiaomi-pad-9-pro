/* loa-drmprops: dump all properties (name=value) of DSI connectors, their CRTC
 * and every plane attached to it. Static musl build, runs on Android and native. */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>
static int fd;
static void dump(uint32_t obj, uint32_t type, const char *label) {
	struct drm_mode_obj_get_properties op = { .obj_id = obj, .obj_type = type };
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return;
	uint32_t ids[256]; uint64_t vals[256]; if (op.count_props > 256) op.count_props = 256;
	op.props_ptr = (uintptr_t)ids; op.prop_values_ptr = (uintptr_t)vals;
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return;
	for (uint32_t i = 0; i < op.count_props; i++) {
		struct drm_mode_get_property gp = { .prop_id = ids[i] };
		if (ioctl(fd, DRM_IOCTL_MODE_GETPROPERTY, &gp)) continue;
		printf("%s %u %s=%llu\n", label, obj, gp.name, (unsigned long long)vals[i]);
	}
}
static uint64_t pval(uint32_t obj, uint32_t type, const char *name) {
	struct drm_mode_obj_get_properties op = { .obj_id = obj, .obj_type = type };
	uint32_t ids[256]; uint64_t vals[256];
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0; if (op.count_props > 256) op.count_props = 256;
	op.props_ptr = (uintptr_t)ids; op.prop_values_ptr = (uintptr_t)vals;
	if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &op)) return 0;
	for (uint32_t i = 0; i < op.count_props; i++) { struct drm_mode_get_property gp = { .prop_id = ids[i] };
		if (!ioctl(fd, DRM_IOCTL_MODE_GETPROPERTY, &gp) && !strcmp(gp.name, name)) return vals[i]; }
	return 0;
}
int main(void) {
	fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC); if (fd < 0) { perror("card0"); return 1; }
	struct drm_set_client_cap cap = { DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1 }; ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap);
	cap.capability = DRM_CLIENT_CAP_ATOMIC; ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap);
	struct drm_mode_card_res res = {0}; uint32_t conns[32];
	ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res); res.count_fbs = res.count_crtcs = res.count_encoders = 0;
	if (res.count_connectors > 32) res.count_connectors = 32; res.connector_id_ptr = (uintptr_t)conns;
	ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res);
	for (uint32_t i = 0; i < res.count_connectors; i++) {
		struct drm_mode_get_connector c = { .connector_id = conns[i] };
		if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) || c.connector_type != DRM_MODE_CONNECTOR_DSI) continue;
		dump(conns[i], DRM_MODE_OBJECT_CONNECTOR, "connector");
		uint64_t crtc = pval(conns[i], DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID"); if (!crtc) continue;
		dump((uint32_t)crtc, DRM_MODE_OBJECT_CRTC, "crtc");
		uint32_t planes[64]; struct drm_mode_get_plane_res pr = { .plane_id_ptr = (uintptr_t)planes, .count_planes = 64 };
		ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &pr);
		for (uint32_t p = 0; p < pr.count_planes; p++)
			if (pval(planes[p], DRM_MODE_OBJECT_PLANE, "CRTC_ID") == crtc) dump(planes[p], DRM_MODE_OBJECT_PLANE, "plane");
	}
	return 0;
}
