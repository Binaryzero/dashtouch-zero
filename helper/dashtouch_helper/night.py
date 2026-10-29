"""Quiet hours: dim the sensor's resting ring on a daily schedule.

The reader's ring has no brightness control — its one LED command takes a
mode, a speed, a color index and a count, nothing else — so "dimmer at
night" means either off or breathing. The device has no clock, so the
schedule lives here in the helper, which already owns the serial port and
runs all day: between `start` and `end` (the Mac's local time) it sends the
same `SET idle_color` / `SET idle_style` lines the web page uses, and when
the window closes it puts the daytime choice back. Nothing in the firmware
changes, and matches and errors still flash — only the resting ring is
touched.

The daytime choice (`day`) is this module's to remember: the device holds
exactly one resting color, so once quiet hours take it over, the page edits
`day` here instead of the device, and the helper restores it in the morning.

Config is a small JSON file next to the labels. Everything here tolerates
it being missing or malformed.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

NIGHT_PATH = pathlib.Path.home() / ".dashtouch" / "night.json"

DURING_CHOICES = ("off", "breathing")
IDLE_KEYS = ("idle_color", "idle_style")

# How often the schedule is re-checked while nothing is happening; a config
# change or a fresh SETTINGS reply re-checks at once.
TICK_SECONDS = 15.0
# A SET line the device hasn't acted on is not repeated more often than this.
RESEND_SECONDS = 60.0

DEFAULTS = {
    "enabled": False,
    "start": "22:00",
    "end": "07:00",
    "during": "off",
    "day": {"idle_color": 3, "idle_style": 1},
}


def parse_hhmm(text) -> int:
    """'HH:MM' (24-hour) -> minutes since midnight. ValueError otherwise."""
    if not isinstance(text, str):
        raise ValueError("time must be text like 22:00")
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"{text!r} isn't a time like 22:00")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"{text!r} isn't a time like 22:00")
    return hours * 60 + minutes


def format_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def in_window(now: int, start: int, end: int) -> bool:
    """Is minute-of-day `now` inside [start, end)? A window that crosses
    midnight (22:00 to 07:00) is the usual case. start == end is an empty
    window — never active, rather than always."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _normalize(raw) -> dict:
    """A config dict with every field present and valid, whatever `raw`
    was: a fresh default set, patched with whichever stored values check
    out. A bad field falls back on its own, not the whole file."""
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if not isinstance(raw, dict):
        return cfg
    cfg["enabled"] = raw.get("enabled") is True
    for key in ("start", "end"):
        try:
            cfg[key] = format_hhmm(parse_hhmm(raw.get(key)))
        except ValueError:
            pass
    if raw.get("during") in DURING_CHOICES:
        cfg["during"] = raw["during"]
    day = raw.get("day") if isinstance(raw.get("day"), dict) else {}
    color, style = day.get("idle_color"), day.get("idle_style")
    if type(color) is int and 0 <= color <= 7:
        cfg["day"]["idle_color"] = color
    if type(style) is int and 1 <= style <= 2:
        cfg["day"]["idle_style"] = style
    return cfg


def desired(cfg: dict, now_min: int) -> dict | None:
    """The resting color/style the device should show at `now_min` under
    `cfg`, or None when quiet hours are off and the device decides."""
    if not cfg["enabled"]:
        return None
    day = cfg["day"]
    if in_window(now_min, parse_hhmm(cfg["start"]), parse_hhmm(cfg["end"])):
        if cfg["during"] == "breathing" and day["idle_color"] != 0:
            return {"idle_color": day["idle_color"], "idle_style": 2}
        return {"idle_color": 0, "idle_style": day["idle_style"]}
    return dict(day)


def plan(cfg: dict, device: dict | None, now_min: int) -> list[tuple[str, int]]:
    """The SET (key, value) pairs that bring a device reporting `device`
    settings in line with `cfg`; [] when quiet hours are off, the device's
    settings aren't known yet, or it already matches."""
    want = desired(cfg, now_min)
    if want is None or not device:
        return []
    return [(k, v) for k, v in want.items() if device.get(k) != v]


class QuietHours:
    """The helper's quiet-hours controller: one per daemon. `tick()` runs
    from the daemon's serial loop; `update()` and `route_idle_setting()`
    from the web server's threads, hence the lock around the config."""

    def __init__(self, daemon, path: pathlib.Path | None = None):
        self._daemon = daemon
        self._path = path  # None: NIGHT_PATH, read at call time so tests can swap it
        self._lock = threading.RLock()
        self._last_tick = 0.0
        self._sent: dict[str, float] = {}
        self.clock = time.localtime  # swapped by tests
        self.cfg = self._load()

    # -- persistence ---------------------------------------------------------
    def _file(self) -> pathlib.Path:
        return self._path or NIGHT_PATH

    def _load(self) -> dict:
        try:
            raw = json.loads(self._file().read_text())
        except (OSError, json.JSONDecodeError):
            raw = None
        return _normalize(raw)

    def _save(self) -> None:
        f = self._file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(self.cfg, indent=2) + "\n")

    # -- time ----------------------------------------------------------------
    def now_minutes(self) -> int:
        lt = self.clock()
        return lt.tm_hour * 60 + lt.tm_min

    def is_active(self) -> bool:
        with self._lock:
            return bool(self.cfg["enabled"]) and in_window(
                self.now_minutes(), parse_hhmm(self.cfg["start"]), parse_hhmm(self.cfg["end"]))

    def snapshot(self) -> dict:
        """The config plus `active`, as /api/status hands it to the page."""
        with self._lock:
            snap = json.loads(json.dumps(self.cfg))
            snap["active"] = self.is_active()
            return snap

    # -- changes from the page -----------------------------------------------
    def update(self, fields) -> dict:
        """Apply any of {enabled, start, end, during}; ValueError names the
        first bad field and nothing is changed. Enabling captures the
        device's current resting choice as `day`; disabling while active
        puts `day` back. Either way the device is re-converged at once."""
        if not isinstance(fields, dict) or not fields:
            raise ValueError("nothing to change")
        unknown = set(fields) - {"enabled", "start", "end", "during"}
        if unknown:
            raise ValueError(f"unknown field {sorted(unknown)[0]!r}")
        new = {}
        if "enabled" in fields:
            if not isinstance(fields["enabled"], bool):
                raise ValueError("enabled must be true or false")
            new["enabled"] = fields["enabled"]
        for key in ("start", "end"):
            if key in fields:
                new[key] = format_hhmm(parse_hhmm(fields[key]))
        if "during" in fields:
            if fields["during"] not in DURING_CHOICES:
                raise ValueError("during must be off or breathing")
            new["during"] = fields["during"]

        with self._lock:
            was_enabled = self.cfg["enabled"]
            was_active = self.is_active()
            self.cfg.update(new)
            device = self._daemon.state.get("settings")
            if self.cfg["enabled"] and not was_enabled and device \
                    and all(k in device for k in IDLE_KEYS):
                # Whatever the ring shows right now is the daytime choice:
                # quiet hours haven't touched it yet.
                self.cfg["day"] = {k: int(device[k]) for k in IDLE_KEYS}
            self._save()
            restore = was_active and not self.cfg["enabled"]
            day = dict(self.cfg["day"])

        if restore:
            # Switched off mid-window: hand the ring back right away rather
            # than leaving it dark until a window that no longer applies.
            device = self._daemon.state.get("settings") or {}
            for key in IDLE_KEYS:
                if device.get(key) != day[key]:
                    self._send(key, day[key], force=True)
        self.tick(force=True)
        return self.snapshot()

    def route_idle_setting(self, key: str, value: int) -> bool:
        """A resting color/style change from the page. With quiet hours off
        it goes straight to the device, as it always has. With them on it
        becomes the daytime choice, and still goes to the device unless
        quiet hours are active right now — then the helper applies it when
        they end. Returns True when the device was told now."""
        with self._lock:
            if not self.cfg["enabled"]:
                self._daemon.send_command(f"SET {key} {value}")
                return True
            self.cfg["day"][key] = int(value)
            self._save()
            active = self.is_active()
        if active:
            return False
        self._daemon.send_command(f"SET {key} {value}")
        return True

    # -- periodic convergence ------------------------------------------------
    def tick(self, force: bool = False) -> None:
        """Send whatever SET lines the schedule calls for. Cheap enough to
        call on every pass of the serial loop: it does real work every
        TICK_SECONDS, or at once when `force` (a config change, a fresh
        SETTINGS reply after a reconnect)."""
        now = time.monotonic()
        if not force and now - self._last_tick < TICK_SECONDS:
            return
        self._last_tick = now
        state = self._daemon.state
        if not state.get("connected"):
            return
        with self._lock:
            cmds = plan(self.cfg, state.get("settings"), self.now_minutes())
        for key, val in cmds:
            self._send(key, val, force)

    def _send(self, key: str, val: int, force: bool) -> None:
        line = f"SET {key} {val}"
        now = time.monotonic()
        last = self._sent.get(line)
        if not force and last is not None and now - last < RESEND_SECONDS:
            return  # asked already; give the device a while before nagging
        self._sent[line] = now
        self._daemon.send_command(line)
        self._daemon.log_event("helper", f"quiet hours: {line}")
