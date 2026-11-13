#!/usr/bin/env python3
"""Put a rebuilt kernel into a copy of the stock boot image.

usage: make-boot.py STOCK_BOOT_DUMP BOOT_GZ_IMG OUT

`boot` is an AVB chain partition on this tablet. The unlocked bootloader
accepts a digest mismatch, but it refuses a boot partition whose vbmeta is
unsigned or whose footer is not at the end of the partition, and then
`fastboot boot` fails as well. So the stock vbmeta and footer stay where they
are, and the gzip-compressed kernel (boot-gz.img of the Kleaf build) replaces
the image in front of them; the uncompressed one is larger than the stock image.
"""
import struct
import sys

stock = bytearray(open(sys.argv[1], "rb").read())
gz = open(sys.argv[2], "rb").read()
assert stock[-64:-60] == b"AVBf" and gz[-64:-60] == b"AVBf"
vbmeta_offset, = struct.unpack(">Q", stock[-64:][20:28])
image_size, = struct.unpack(">Q", gz[-64:][12:20])
assert image_size <= vbmeta_offset, "kernel does not fit in front of the stock vbmeta"
stock[:vbmeta_offset] = gz[:image_size] + bytes(vbmeta_offset - image_size)
open(sys.argv[3], "wb").write(stock)
