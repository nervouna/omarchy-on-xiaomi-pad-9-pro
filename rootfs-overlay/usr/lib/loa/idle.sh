#!/bin/sh
# Idle steps, called by hypridle (~/.config/hypr/hypridle.conf) as the user.
#   dim          on battery: ask loa-autobrightness to fade the backlight to its minimum
#   undim        back to the brightness from before
#   battery-off  on battery: screen off
#   off          screen off
#   on           screen on, if it is off
# The power source is read when a step fires. On external power "dim" and
# "battery-off" do nothing, which leaves Omarchy's screensaver (150 s) and the
# 5 min screen-off as they were.
# Testing on the USB cable: `touch $XDG_RUNTIME_DIR/loa-idle-on-battery` makes the
# steps behave as on battery.
R=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
DIM=$R/loa-idle-dim

on_battery() {
    [ -e "$R/loa-idle-on-battery" ] || [ "$(cat /sys/class/power_supply/usb/online 2>/dev/null)" != 1 ]
}
dpms() {
    hyprctl eval "hl.dispatch(hl.dsp.dpms({ action = \"$1\" }))" >/dev/null
}
screen_off() {
    hyprctl monitors -j | jq -e 'length > 0 and all(.[]; .dpmsStatus == false)' >/dev/null 2>&1
}

case $1 in
    dim)         if on_battery; then : > "$DIM"; fi ;;
    undim)       rm -f "$DIM" ;;
    battery-off) if on_battery; then dpms disable; fi ;;
    off)         dpms disable ;;
    # hypridle also runs this for steps that did nothing (external power, or the
    # screensaver launch counting as activity): leave a lit screen alone.
    on)          if screen_off; then dpms enable; fi ;;
    *)           echo "usage: $0 dim|undim|battery-off|off|on" >&2; exit 2 ;;
esac
