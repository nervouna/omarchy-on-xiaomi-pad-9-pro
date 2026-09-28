/* Native RAM-only Bionic THP harness. Never run alongside Android touch HAL.
 * --check loads libraries (including their constructors), but never calls main.
 * Run --check in the supplied chroot BEFORE binding /dev or /sys.
 */
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--check") && strcmp(argv[1], "--run"))) {
        fprintf(stderr, "usage: loa-thp-launcher --check|--run\n");
        return 64;
    }
    const char *paths[] = {
        "/odm/lib64/libtouchreport.so",
        "/odm/lib64/libtouchreport_alg.so",
        "/odm/lib64/libtouchreport_hal.so",
        "/odm/lib64/libtouchreport_sensor.so"
    };
    void *main_handle = NULL;
    for (unsigned i = 0; i < sizeof(paths)/sizeof(paths[0]); ++i) {
        void *handle = dlopen(paths[i], RTLD_NOW | RTLD_LOCAL);
        if (!handle) {
            fprintf(stderr, "THP load failed: %s: %s\n", paths[i], dlerror());
            return 1;
        }
        if (!i) main_handle = handle;
        fprintf(stderr, "THP loaded: %s\n", paths[i]);
    }
    dlerror();
    int (*vendor_main)(int, char **) = (int (*)(int, char **))dlsym(main_handle, "main");
    const char *error = dlerror();
    if (error || !vendor_main) {
        fprintf(stderr, "THP main lookup failed: %s\n", error ? error : "null symbol");
        return 1;
    }
    if (!strcmp(argv[1], "--check")) {
        fprintf(stderr, "THP check passed; constructors ran; vendor main NOT called\n");
        return 0;
    }
    char name[] = "touch_report";
    char *vendor_argv[] = {name, NULL};
    fprintf(stderr, "THP starting vendor main for touch ID 0\n");
    return vendor_main(1, vendor_argv);
}
