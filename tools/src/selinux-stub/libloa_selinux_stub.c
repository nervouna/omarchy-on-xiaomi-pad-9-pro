/*
 * LD_PRELOAD stub for Android daemons running natively without an SELinux
 * policy (the Omarchy host loads none). Answers the libselinux calls used by
 * servicemanager/vndservicemanager/hwservicemanager and HALs with "allowed".
 * Built freestanding (no libc NEEDED); strdup/free resolve from Bionic.
 */
extern char *strdup(const char *);
extern void free(void *);
#define EXPORT __attribute__((visibility("default")))
static char handle_dummy;

EXPORT int getcon(char **con) { *con = strdup("u:r:loa_native:s0"); return 0; }
EXPORT int getpidcon(int pid, char **con) { (void)pid; *con = strdup("u:r:loa_native:s0"); return 0; }
EXPORT int getprevcon(char **con) { return getcon(con); }
EXPORT void freecon(char *con) { free(con); }
EXPORT int selinux_status_open(int fallback) { (void)fallback; return 0; }
EXPORT int selinux_status_updated(void) { return 0; }
EXPORT void selinux_status_close(void) {}
EXPORT void selinux_set_callback(int type, void *cb) { (void)type; (void)cb; }
EXPORT int selinux_log_callback(int type, const char *fmt, ...) { (void)type; (void)fmt; return 0; }
EXPORT int selinux_vendor_log_callback(int type, const char *fmt, ...) { (void)type; (void)fmt; return 0; }
EXPORT int selinux_check_access(const char *s, const char *t, const char *c, const char *p, void *a) {
	(void)s; (void)t; (void)c; (void)p; (void)a; return 0;
}
EXPORT void *selinux_android_service_context_handle(void) { return &handle_dummy; }
EXPORT void *selinux_android_vendor_service_context_handle(void) { return &handle_dummy; }
EXPORT void *selinux_android_hw_service_context_handle(void) { return &handle_dummy; }
EXPORT void *selinux_android_keystore2_key_context_handle(void) { return &handle_dummy; }
EXPORT int selabel_lookup(void *h, char **con, const char *key, int type) {
	(void)h; (void)key; (void)type; *con = strdup("u:object_r:loa_service:s0"); return 0;
}
EXPORT void selabel_close(void *h) { (void)h; }
