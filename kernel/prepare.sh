#!/bin/sh
# Changes to the Android common kernel tree before the build. Run in the root of
# the repo checkout (the directory that holds common/ and build/).
#   prepare.sh VERSION   (kernel/VERSION: the release becomes 6.12.69-android16-6-<VERSION>-4k)
set -e
V=$1
# With IPC namespaces on, rust_binder.ko (a module) calls two symbols the kernel
# does not export: export them and keep them from being trimmed. This is a gap in
# the Android common kernel, not specific to the tablet.
echo 'EXPORT_SYMBOL_GPL(put_ipc_ns);' >> common/ipc/namespace.c
echo 'EXPORT_SYMBOL_GPL(init_ipc_ns);' >> common/ipc/msgutil.c
printf '  %s\n' init_ipc_ns put_ipc_ns >> common/gki/aarch64/symbols/base
# A release string of our own. Without --config=stamp Kleaf writes "-maybe-dirty".
grep -q "echo '-maybe-dirty'" build/kernel/kleaf/impl/stamp.bzl
sed -i "s/echo '-maybe-dirty'/echo '-$V'/" build/kernel/kleaf/impl/stamp.bzl
