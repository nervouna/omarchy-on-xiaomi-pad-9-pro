# 在小米平板 9 Pro 上运行 Omarchy

[English](README.md) | **简体中文**

让 [Omarchy](https://omarchy.org)（Arch Linux ARM + Hyprland）**原生**运行在小米平板 9 Pro
（代号 `shuntian`，高通 SM8845）上，开机直接进入桌面。不依赖 Android 框架，不是 Android 里的
chroot，也不是 PRoot：平板在原厂 Android GKI 内核上直接运行 systemd、Hyprland 和 Omarchy
桌面。Android 自带的厂商守护进程（音频、蓝牙、传感器、触控）在旁边一个小小的“服务孤岛”里运行。

> **状态：开发中。** 已在两台测试平板上日常使用。目前给一台新平板安装，仍然需要一台已经跑着本项目的平板（见[路线图](#路线图)）。

## 前提条件

> [!IMPORTANT]
> - **已解锁 Bootloader。** 本项目不负责解锁，请按小米官方流程操作。
> - **小米平板 9 Pro（`shuntian`），原厂 ROM `OS4.0.5.0.XFPCNXM`**（国行，Android 17，
>   GKI 内核 6.12.69，`android16-6.12` 分支）。本项目复用这一版本的内核、模块、固件和厂商守护进程：换其他版本或机型，
>   不做移植工作就无法运行。已在 8 GB 和 12 GB 两个版本上测试。
> - **一台 Mac**，装好 Android platform-tools、`zstd`、`lz4` 和 `python3`。主机端脚本是为 macOS 写的。
> - **原厂 Android 上的 Magisk root**，只需一次，用来采集你这台平板的 Android 属性
>   （`tools/capture-android-props.sh`）。
> - 暂时还需要 **一台已经运行本项目的平板**，用来制作根文件系统镜像。

## 可用功能

| 功能 | 状态 |
|---|---|
| 开机自动进入 Omarchy；需要时仍可启动 Android | 可用 |
| 屏幕 3200×2136 @ 120 Hz，GPU（Adreno 829，KGSL Mesa，GL + Vulkan） | 可用 |
| 触控、亮度、自动亮度、息屏、s2idle 休眠 | 可用 |
| Wi-Fi、蓝牙（含 A2DP 耳机） | 可用 |
| 扬声器、内置麦克风（PipeWire → 原厂高通音频栈） | 可用 |
| 小米磁吸键盘 + 触控板、键盘背光、合盖/开盖 | 可用 |
| 充电（电池认证、PPS 快充约 34 W） | 可用；充电器认证（满功率）进行中 |
| Xiaomi Focus Pencil Pro 触控笔当指针用（自动配对、悬停、点按、拖动、双击 = 右键） | 可用 |
| 中文输入（fcitx5） | 可用 |
| 摄像头、基带、耳机孔、轻触唤醒、自动旋转 | 尚未实现 |

详情与注意事项：[docs/status.md](docs/status.md)（英文）。

## 限制

本项目运行在原厂内核和固件上，因此有一些硬性限制：

- **没有 user namespace。** 依赖它的东西（Flatpak/bubblewrap、rootless 容器、systemd 的
  `PrivateUsers=`）都不能用；overlay 为受影响的服务关闭了 `PrivateUsers=`。Chromium 的 setuid 沙箱可以用。
- **没有深度睡眠。** 深度休眠在唤醒时出错（PMIC 报错），所以只用 s2idle，仅在电池供电时休眠，
  休眠期间关闭 Wi-Fi 和蓝牙。开盖不会唤醒：请按键盘或电源键。
- **没有内存压力信息**（Bootloader 命令行带 `cgroup_disable=pressure`）：无法使用
  systemd-oomd，改用 zram + earlyoom。8 GB 版本跑重型 Electron 应用比较吃紧，12 GB 比较从容。
- **没有 AF_ALG 加密套接字**：不能用 iwd，改用 NetworkManager。
- **没有 SysV IPC**：原版 `fakeroot`（以及依赖它的 `makepkg`/AUR 构建）无法运行，改用 AUR 的 `fakeroot-tcp`。
- **没有 devtmpfs**：`/dev` 由 mdev 填充，udev 叠加在上面。
- **Aquamarine 打了补丁**：升级 Hyprland 需要用 `patches/` 重新编译 Aquamarine
  （见 [docs/maintenance.md](docs/maintenance.md)）。

## 我的日常配置

作者日常在上面跑的：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)
（TUN 模式，arm64 `.deb` 手动解包安装）、通过 Omarchy 的 mise 代理选择器安装的 Codex、微信，
以及飞书（Lark，以原生 Wayland 方式运行：`--ozone-platform=wayland --enable-wayland-ime`，
这样 fcitx5 能用，也不会被双重缩放）。这些都不在仓库里，只是展示这套系统能承载什么。

## 路线图

- **从零安装**：目前新平板要用另一台已运行本项目的平板制作的镜像来安装。目标是一个从零构建
  （Arch Linux ARM + Omarchy + 本 overlay）、任何人都能刷的镜像。
- **Focus Pencil Pro 触控笔**：运动传感器（加速度计 + 陀螺仪，用于隔空手势）、触觉反馈、压感/倾斜、防误触。
- **充电**：小米充电器认证，实现满功率充电。
- **摄像头**、**基带**、**耳机孔**。
- **轻触唤醒**、**开盖唤醒**、**自动旋转**。

## 安全第一

**第一原则：永远不能丢掉 Fastboot。** 本项目不会写 Bootloader，工具只写 `init_boot_<slot>`、
`ramdump` 以及（可选）单独划出来的 `omarchy` 分区。如果连续 3 次启动都没进入桌面，第一阶段 init
会自动重启进 Fastboot；刷回原厂 `init_boot` 即可恢复 Android。

即便如此：这会刷写你设备上的分区，并可能清除 Android 数据（重新分区会清除）。请使用一台坏了也不心疼的平板。
本项目不提供任何担保，见 [LICENSE](LICENSE)。

## 安装（前提是你已有一台能用的平板）

按 [docs/runbook.md](docs/runbook.md)（英文）操作。简要步骤：

```
tools/capture-android-props.sh          # 原厂 Android + Magisk：采集本机属性快照
tools/make-image.sh --clean --reset-hypr --apply   # 在已运行的平板上：制作母版根镜像
python3 boot/build-init-boot.py         # 用原厂 init_boot 制作第一阶段启动镜像
tools/install.sh images/omarchy-clean-*.img.zst    # 新平板进入 Fastboot 后安装
tools/personalize.sh                    # 生成新身份（Wi-Fi MAC、主机密钥、各类 ID）
tools/apply-overlay.sh                  # 把系统同步到本仓库的版本；添加你的 SSH 公钥
tools/repartition.sh 64 --apply         # 可选：根分区从 17 GiB 扩到 64 GiB
```

你需要在 `keys/` 里放自己的 SSH 密钥（仓库不附带任何密钥），并在 `images/` 里放官方 ROM 中的原厂 `init_boot`。

## 目录结构

| 路径 | 内容 |
|---|---|
| `boot/` | 第一阶段 init（busybox）+ `loa-helper`，以及 `build-init-boot.py`：把它们和原厂第一阶段 ramdisk 打包成 `init_boot` |
| `rootfs-overlay/` | 本项目管理的系统文件（systemd 单元、`usr/lib/loa` 里的守护进程、`/usr/share/loa/hypr/loa.lua` 设备设置、`/etc` 下的 PipeWire/WirePlumber 配置）。`tools/apply-overlay.sh` 负责安装/更新，替换前会备份（`--diff` 可预览） |
| `user-defaults/` | 用户可以自定义的文件（hypridle、Chromium 参数、fcitx5 配置）：只在缺失时安装，从不覆盖 |
| `tools/` | Mac 端脚本：`tssh`（经 USB 的 SSH）、安装/镜像/重新分区/个性化，以及编译原生辅助程序的 `build.sh`（`tools/src`） |
| `patches/` | Aquamarine 补丁（拆分主平面、DMA-heap 扫描输出、强制 MODE_ID） |
| `reference/` | 从原厂 Android 采集的资料（键盘/触控笔数据包、DRM/SDE 状态、logcat 摘录）和内核崩溃日志 |
| `docs/` | 安装手册、状态、维护说明和完整的工程日志（英文） |
| `images/`、`keys/` | 仅本地（git 忽略）：启动镜像和根镜像、你的 SSH 密钥 |

（文件名里的 “LoA” 是项目最初的工作代号。）

## 不在仓库里的东西

- **小米/高通二进制文件**：原厂 `init_boot`、NDK 辅助程序链接的厂商库、固件。请从官方 ROM 或你自己的平板获取
  （`images/README.md`、`tools/fetch-device-libs.sh`）。
- **设备身份信息**：Android 属性快照（含序列号）、Wi-Fi MAC、SSH 密钥。每次安装各自生成或采集。
- **根文件系统镜像**：体积有好几 GB。

## 致谢

- [Omarchy](https://omarchy.org)、[Hyprland](https://hyprland.org) 和
  [Arch Linux ARM](https://archlinuxarm.org)。
- [libssc](https://codeberg.org/DylanVanAssche/libssc)，提供了逆向得到的高通传感器协议定义。
- 大量借助 AI 编程助手完成；[工程日志](docs/engineering-log.md)（英文）记录了完整过程。

本项目与小米、高通及 Omarchy 项目均无关联，也未获其认可。第三方组件见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 许可证

[MIT](LICENSE) © 2026 Xiaoyu Guan
