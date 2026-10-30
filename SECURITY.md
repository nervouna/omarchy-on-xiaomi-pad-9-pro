# Security

This project builds and installs the operating system of a tablet. Its scripts flash boot partitions over Fastboot, build a root image that runs systemd, Hyprland and Android's vendor daemons as root, and set up SSH access to the tablet with the owner's key. Each tablet also has its own identity (serial numbers in the Android property snapshot, the Wi-Fi MAC, SSH host keys), which must never end up in the repository or in an image meant for someone else. The repository ships no keys: `keys/` and `images/` are local only and git-ignored, and `tools/check-public.sh` scans what git would publish.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub: **Security → Report a vulnerability** on this repository ([direct link](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/security/advisories/new)). Include what you did, what happened, and the commit you tested. Do not attach your property snapshot, keys or images.

You will get an answer within a week. Fixes land on `main`; there are no maintained release branches.

## In scope

- A way to get a shell or root on a running tablet without the owner's SSH key
- Files tracked in this repository, or files the build or install scripts put into an image, that carry keys, device identifiers, credentials or personal data
- A way for the install scripts to write partitions other than the ones the README names
- A way for the image build to use sources or packages other than the pinned and signed ones in `builder/`

## Out of scope

- Anything that needs physical access to the tablet: its bootloader is unlocked by design, which already gives full control to whoever holds it
- Anything that needs access to the owner's Mac or build machine
- Weaknesses in the stock Android kernel, Xiaomi or Qualcomm firmware and vendor daemons, Omarchy, Hyprland or Arch Linux ARM packages; report those upstream
- The limits listed in the README, such as the missing user namespaces
