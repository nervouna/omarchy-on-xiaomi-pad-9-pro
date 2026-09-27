/*
 * loa-xtouch: poke Xiaomi touch modes through /dev/xiaomi-touch.
 * ABI reverse-engineered from xiaomi_touch.ko (xiaomi_touch_dev_ioctl / xiaomi_touch_mode):
 *   ioctl _IOWR('T', 0, 1032), struct { u8 touch_id; u8 cmd; u16 mode; u16 len; u16 pad; s32 data[256]; }
 *   cmd 0 = set value (data[0]), cmd 1..4 = get (current/default/min/max) into data[0].
 * usage: loa-xtouch get MODE [CMD] | set MODE VALUE
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
struct xt { uint8_t touch_id, cmd; uint16_t mode, len, pad; int32_t data[256]; };
_Static_assert(sizeof(struct xt) == 1032, "size");
int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "usage: loa-xtouch get MODE [CMD] | set MODE VALUE\n"); return 2; }
	int fd = open("/dev/xiaomi-touch", O_RDWR);
	if (fd < 0) { perror("open"); return 1; }
	/* select touch id 0 on this fd (ioctl nr 3; nr 2 selects the mmap area) */
	if (ioctl(fd, _IO('T', 3), 0) < 0) perror("select touch id");
	struct xt x; memset(&x, 0, sizeof x);
	x.mode = atoi(argv[2]); x.len = 1;
	if (!strcmp(argv[1], "set") && argc == 4) { x.cmd = 0; x.data[0] = atoi(argv[3]); }
	else if (!strcmp(argv[1], "get")) x.cmd = argc > 3 ? atoi(argv[3]) : 1;
	else return 2;
	int r = ioctl(fd, _IOWR('T', 0, struct xt), &x);
	printf("%s mode %u cmd %u -> ret %d data[0..3] = %d %d %d %d\n", argv[1], x.mode, x.cmd, r, x.data[0], x.data[1], x.data[2], x.data[3]);
	return r < 0;
}
