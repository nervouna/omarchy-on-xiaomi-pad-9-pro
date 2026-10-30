# Contributing

This is a personal project for one tablet model, but bug reports and fixes are welcome, especially from other Xiaomi Pad 9 Pro owners.

## Issues

- **Bugs:** use the bug report form. Give your tablet's RAM size and ROM build, the commit you built from, what happened and what you expected. Logs help (`journalctl`, `dmesg`), but remove serial numbers, MAC addresses and other identifiers first.
- **Security problems:** report them privately, see [SECURITY.md](SECURITY.md).
- **Ideas and other devices:** open an issue to discuss it first. The project stays small on purpose, and it targets one tablet on one ROM build (`OS4.0.5.0.XFPCNXM`); ports to other models or builds are out of scope here.

## How the project is developed

The author develops the port with a lot of help from AI coding agents. [docs/engineering-log.md](docs/engineering-log.md) records what was tried and why; [docs/status.md](docs/status.md) and [docs/maintenance.md](docs/maintenance.md) are kept up to date with what works and how to maintain it. A change that alters what works or how to install should update those docs and both READMEs (`README.md` and `README.zh-CN.md`).

Before you push, run `tools/check-public.sh`. It must print `check-public: clean`: no keys, device identifiers, personal names or home paths in anything git would publish. Never commit files from `images/` or `keys/`, the Android property snapshot, or vendor binaries.

Never change what the tools write to the tablet without saying so plainly in the pull request: the install path must keep Fastboot reachable.

## Pull requests

Describe the problem, what you changed, and how you tested it: on which tablet (RAM size, ROM build), with which commands, and what you checked on the device. Keep one change per pull request.
