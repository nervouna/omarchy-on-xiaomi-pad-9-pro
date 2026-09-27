#!/bin/sh
# USB gadget: ACM serial (ttyGS0) + ECM network (usb0), same IDs as the RAM probes.
# Used by stage-1 rescue and by loa-usb-gadget.service in the booted system.
G=/config/usb_gadget/loa
[ -d /config/usb_gadget ] || mount -t configfs configfs /config 2>/dev/null
[ -e $G/UDC ] && [ -n "$(cat $G/UDC 2>/dev/null)" ] && exit 0
echo peripheral > /sys/bus/platform/devices/a600000.ssusb/mode 2>/dev/null
udc=""
for i in $(seq 1 150); do udc=$(ls /sys/class/udc 2>/dev/null | head -1); [ -n "$udc" ] && break; sleep 0.1; done
[ -n "$udc" ] || { echo "<3>loa-usb: no UDC" > /dev/kmsg; exit 1; }
mkdir -p $G/strings/0x409 $G/configs/c.1/strings/0x409 $G/functions/acm.usb0 $G/functions/ecm.usb0
echo 0x1d6b > $G/idVendor; echo 0x0104 > $G/idProduct; echo 0x0200 > $G/bcdUSB
echo 0xef > $G/bDeviceClass; echo 0x02 > $G/bDeviceSubClass; echo 0x01 > $G/bDeviceProtocol
echo LOA-RAM-PROBE > $G/strings/0x409/serialnumber
echo LoA > $G/strings/0x409/manufacturer
echo "LoA Omarchy shuntian" > $G/strings/0x409/product
echo "Omarchy debug" > $G/configs/c.1/strings/0x409/configuration
echo 250 > $G/configs/c.1/MaxPower
echo 02:00:00:77:00:01 > $G/functions/ecm.usb0/host_addr
echo 02:00:00:77:00:02 > $G/functions/ecm.usb0/dev_addr
ln -s $G/functions/acm.usb0 $G/configs/c.1/ 2>/dev/null
ln -s $G/functions/ecm.usb0 $G/configs/c.1/ 2>/dev/null
echo "$udc" > $G/UDC
# ttyGS0 node (no devtmpfs)
if [ ! -c /dev/ttyGS0 ] && [ -r /sys/class/tty/ttyGS0/dev ]; then
    IFS=: read -r ma mi < /sys/class/tty/ttyGS0/dev; mknod -m 600 /dev/ttyGS0 c "$ma" "$mi"
fi
echo "<3>loa-usb: gadget bound to $udc" > /dev/kmsg
