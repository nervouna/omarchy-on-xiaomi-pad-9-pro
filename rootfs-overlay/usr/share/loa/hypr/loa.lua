-- LoA device settings for the Xiaomi Pad 9 Pro (shuntian), owned by the
-- omarchy-on-xiaomi-pad-9-pro overlay (tools/apply-overlay.sh rewrites this file).
-- Loaded from ~/.config/hypr/hyprland.lua right after Omarchy's defaults and
-- BEFORE the personal files (hypr/monitors, input, bindings, looknfeel,
-- autostart), so anything set there wins. Don't edit here; override there.

-- Display ---------------------------------------------------------------------
-- Native panel: 3200x2136 DSI, dual-LM (Aquamarine splits the primary plane,
-- AQ_DRM_SPLIT_PRIMARY). 120 Hz is the stock default mode.
hl.env("GDK_SCALE", "2")
hl.monitor({ output = "DSI-1", mode = "3200x2136@120", position = "0x0", scale = 2, transform = 0 })
-- SDE writeback connectors (Virtual-1/2) are not real displays; Hyprland would
-- otherwise cycle through their modes, allocating swapchains and failing commits.
hl.monitor({ output = "Virtual-1", disabled = true })
hl.monitor({ output = "Virtual-2", disabled = true })

-- Touch -----------------------------------------------------------------------
-- NT36536 touchscreen: raw X spans the panel's short side (top = max), raw Y the
-- long side (left = 0). Transform 3 = calibration {0 1 0 -1 0 1}. Hyprland
-- always sets the libinput matrix itself, overriding udev defaults.
hl.config({
  input = {
    touchdevice = {
      transform = 3,
      output = "DSI-1",
    },
  },
})

-- Pen (Xiaomi Focus Pencil Pro via the NT36536 pen devices) -----------------------
-- Same axis layout as the touchscreen (transform 3), locked to the panel. Acts as an
-- absolute pointer: hover moves the cursor, the tip clicks.
hl.config({
  input = {
    tablet = {
      transform = 3,
      output = "DSI-1",
    },
  },
})

-- Keys ------------------------------------------------------------------------
-- The power key is handled by loa-power-key.service (reads pmic_pwrkey directly;
-- safe screen-off). The system menu stays in the Omarchy menu.
hl.unbind("XF86PowerOff")
-- Super+Space keeps Omarchy's own binding: the packaged shell registers no
-- omarchy:menu global shortcut to rebind it to.

-- Session processes ---------------------------------------------------------------
hl.on("hyprland.start", function()
  -- Voxtype is optional until a model has been downloaded; its small manager is a
  -- no-op without a model and replaces the unavailable systemd user unit.
  hl.exec_cmd("omarchy-voxtype-daemon start")
  -- Screen off after idle (~/.config/hypr/hypridle.conf).
  hl.exec_cmd("hypridle")
end)

-- Look & rendering ------------------------------------------------------------------
-- Carried over unchanged from the earlier (PRoot-era) looknfeel.lua so behaviour
-- doesn't change with the restructure. TODO: review natively (vfr=false keeps
-- rendering continuous; the cursor/scanout settings may no longer be needed).
hl.config({
  decoration = {
    blur   = { enabled = false },
    shadow = { enabled = false },
  },
})
hl.config({
  render = { direct_scanout = false },
  cursor = {
    no_hardware_cursors = true,
    use_cpu_buffer = true,
    hide_on_key_press = false,
    hide_on_touch = false,
    inactive_timeout = 0,
  },
  xwayland = { enabled = true },
  debug = {
    damage_tracking = 2,
    vfr = false,
    enable_stdout_logs = false,
  },
})
hl.env("NO_AT_BRIDGE", "1")
hl.env("QT_ACCESSIBILITY", "0")
hl.env("GTK_A11Y", "none")
hl.env("LANG", "C.UTF-8")
hl.env("LC_ALL", "C.UTF-8")
hl.env("XCURSOR_THEME", "Adwaita")
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.config({ misc = { disable_watchdog_warning = true } })
