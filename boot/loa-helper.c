/*
 * loa-helper: static helper for the LoA stage-1 init.
 *   loa-helper bootloader          reboot straight into Fastboot (RESTART2 "bootloader")
 *   loa-helper keys MS             exit 0 if KEY_VOLUMEUP is held at any time within MS
 *                                  milliseconds (boot menu: Volume Up -> Android), else 1.
 *   loa-helper watchdog SECONDS    daemonize; after SECONDS reboot to Fastboot unless
 *                                  loa-watchdog-disarm exists in the /run tmpfs.
 * The watchdog keeps an fd on /run opened *before* switch_root moves the mount,
 * so it still sees the real /run after the old initramfs has been emptied.
 */
#include <fcntl.h>
#include <linux/reboot.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <dirent.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <time.h>

static void kmsg(const char *s) {
	int fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
	if (fd >= 0) { dprintf(fd, "<3>loa-helper: %s\n", s); close(fd); }
}
static void to_bootloader(void) {
	sync();
	syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_RESTART2, "bootloader");
	reboot(RB_AUTOBOOT);
}
static int volume_up_held(void) {
	DIR *d = opendir("/dev/input");
	struct dirent *e; int held = 0;
	if (!d) return 0;
	while (!held && (e = readdir(d))) {
		if (strncmp(e->d_name, "event", 5)) continue;
		char p[64]; snprintf(p, sizeof p, "/dev/input/%s", e->d_name);
		int fd = open(p, O_RDONLY | O_CLOEXEC);
		if (fd < 0) continue;
		unsigned char keys[KEY_MAX / 8 + 1] = {0};
		if (ioctl(fd, EVIOCGKEY(sizeof keys), keys) >= 0 && (keys[KEY_VOLUMEUP / 8] >> (KEY_VOLUMEUP % 8) & 1)) held = 1;
		close(fd);
	}
	closedir(d);
	return held;
}
int main(int argc, char **argv) {
	if (argc == 3 && !strcmp(argv[1], "keys")) {
		int ms = atoi(argv[2]);
		for (int t = 0; t <= ms; t += 50) {
			if (volume_up_held()) { kmsg("Volume Up held: boot Android"); return 0; }
			struct timespec ts = {0, 50 * 1000000}; nanosleep(&ts, NULL);
		}
		return 1;
	}
	if (argc == 2 && !strcmp(argv[1], "bootloader")) { kmsg("reboot to bootloader"); to_bootloader(); return 1; }
	if (argc == 3 && !strcmp(argv[1], "watchdog")) {
		int secs = atoi(argv[2]);
		int run = open("/run", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
		if (secs <= 0 || run < 0) return 2;
		if (fork() != 0) return 0;
		setsid();
		for (int i = 0; i < 3; i++) close(i);
		for (int t = 0; t < secs; t++) {
			sleep(1);
			if (faccessat(run, "loa-watchdog-disarm", F_OK, 0) == 0) { kmsg("watchdog disarmed"); return 0; }
		}
		kmsg("dev watchdog expired, rebooting to bootloader");
		to_bootloader();
		return 1;
	}
	fprintf(stderr, "usage: loa-helper bootloader | keys MS | watchdog SECONDS\n");
	return 2;
}
