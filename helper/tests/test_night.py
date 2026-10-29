import json
import time

import pytest

from dashtouch_helper import night


def minutes(h, m=0):
    return h * 60 + m


# -- parsing and the window ---------------------------------------------------

def test_parse_hhmm_accepts_24h_times():
    assert night.parse_hhmm("22:00") == minutes(22)
    assert night.parse_hhmm("07:30") == minutes(7, 30)
    assert night.parse_hhmm("0:05") == 5


@pytest.mark.parametrize("bad", ["", "25:00", "22:60", "10pm", "22", 2200, None, "22:00:00"])
def test_parse_hhmm_rejects_garbage(bad):
    with pytest.raises(ValueError):
        night.parse_hhmm(bad)


def test_window_same_day():
    s, e = minutes(13), minutes(15)
    assert night.in_window(minutes(13), s, e)
    assert night.in_window(minutes(14, 59), s, e)
    assert not night.in_window(minutes(15), s, e)
    assert not night.in_window(minutes(12, 59), s, e)


def test_window_crossing_midnight():
    s, e = minutes(22), minutes(7)
    assert night.in_window(minutes(23), s, e)
    assert night.in_window(0, s, e)
    assert night.in_window(minutes(6, 59), s, e)
    assert not night.in_window(minutes(7), s, e)
    assert not night.in_window(minutes(12), s, e)


def test_window_with_equal_ends_is_never_active():
    assert not night.in_window(minutes(3), minutes(3), minutes(3))


# -- what the device should show ---------------------------------------------

def cfg(**over):
    c = {"enabled": True, "start": "22:00", "end": "07:00", "during": "off",
         "day": {"idle_color": 3, "idle_style": 1}}
    c.update(over)
    return c


DAY = {"idle_color": 3, "idle_style": 1, "press_enter": True, "fp_swap": False}


def test_plan_does_nothing_when_disabled():
    assert night.plan(cfg(enabled=False), DAY, minutes(23)) == []


def test_plan_does_nothing_without_device_settings():
    assert night.plan(cfg(), None, minutes(23)) == []


def test_plan_turns_the_ring_off_inside_the_window():
    assert night.plan(cfg(), DAY, minutes(23)) == [("idle_color", 0)]


def test_plan_breathing_keeps_the_day_color():
    assert night.plan(cfg(during="breathing"), DAY, minutes(23)) == [("idle_style", 2)]


def test_plan_breathing_with_day_color_off_stays_off():
    off = {"idle_color": 0, "idle_style": 1}
    assert night.plan(cfg(during="breathing", day=off), dict(DAY, idle_color=0), minutes(23)) == []


def test_plan_restores_the_day_choice_outside_the_window():
    assert night.plan(cfg(), dict(DAY, idle_color=0), minutes(9)) == [("idle_color", 3)]
    assert night.plan(cfg(during="breathing"), dict(DAY, idle_style=2), minutes(9)) == [("idle_style", 1)]


def test_plan_is_quiet_once_converged():
    assert night.plan(cfg(), dict(DAY, idle_color=0), minutes(23)) == []
    assert night.plan(cfg(), DAY, minutes(9)) == []


# -- the controller -----------------------------------------------------------

class FakeDaemon:
    """Just enough daemon for QuietHours: state, a send_command that
    mirrors the device's SET_OK into state, and an event log."""

    def __init__(self, settings=DAY, connected=True):
        self.state = {"connected": connected,
                      "settings": dict(settings) if settings else None}
        self.sent = []
        self.events = []

    def send_command(self, line):
        self.sent.append(line)
        _, key, val = line.split()
        self.state["settings"][key] = int(val)

    def log_event(self, direction, text):
        self.events.append((direction, text))


def at(h, m=0):
    """A stand-in for QuietHours.clock: always h:m local time."""
    return lambda: time.struct_time((2026, 1, 1, h, m, 0, 3, 1, -1))


def test_fresh_config_is_disabled_with_defaults(tmp_path):
    q = night.QuietHours(FakeDaemon(), tmp_path / "night.json")
    assert q.snapshot() == {"enabled": False, "start": "22:00", "end": "07:00",
                            "during": "off", "day": {"idle_color": 3, "idle_style": 1},
                            "active": False}


def test_garbage_config_falls_back_field_by_field(tmp_path):
    p = tmp_path / "night.json"
    p.write_text("{not json")
    assert night.QuietHours(FakeDaemon(), p).snapshot()["enabled"] is False
    p.write_text(json.dumps({"enabled": True, "start": "99:99", "end": "6:30",
                             "during": "disco", "day": {"idle_color": 42, "idle_style": 2}}))
    snap = night.QuietHours(FakeDaemon(), p).snapshot()
    assert snap["enabled"] is True
    assert snap["start"] == "22:00" and snap["end"] == "06:30"
    assert snap["during"] == "off"
    assert snap["day"] == {"idle_color": 3, "idle_style": 2}


def test_enabling_captures_the_device_choice_as_day_and_dims_at_once(tmp_path):
    d = FakeDaemon(settings=dict(DAY, idle_color=2, idle_style=2))
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    snap = q.update({"enabled": True})
    assert snap["day"] == {"idle_color": 2, "idle_style": 2}
    assert snap["active"] is True
    assert d.sent == ["SET idle_color 0"]
    assert json.loads((tmp_path / "night.json").read_text())["enabled"] is True
    assert ("helper", "quiet hours: SET idle_color 0") in d.events


def test_enabling_outside_the_window_leaves_the_device_alone(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(12)
    q.update({"enabled": True})
    assert d.sent == []


def test_disabling_while_active_restores_the_day_choice(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    d.sent.clear()
    q.update({"enabled": False})
    assert d.sent == ["SET idle_color 3"]


def test_update_validates_fields_and_changes_nothing_on_error(tmp_path):
    q = night.QuietHours(FakeDaemon(), tmp_path / "night.json")
    for bad in ({"start": "25:00"}, {"during": "dim"}, {"enabled": "yes"},
                {"brightness": 1}, {}, []):
        with pytest.raises(ValueError):
            q.update(bad)
    assert q.snapshot()["enabled"] is False
    assert not (tmp_path / "night.json").exists()


def test_changing_the_window_reconverges_immediately(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(20)
    q.update({"enabled": True})
    assert d.sent == []
    q.update({"start": "19:30"})
    assert d.sent == ["SET idle_color 0"]
    assert q.snapshot()["start"] == "19:30"


def test_switching_to_breathing_mid_window_brings_the_color_back(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    d.sent.clear()
    q.update({"during": "breathing"})
    assert d.sent == ["SET idle_color 3", "SET idle_style 2"]


def test_tick_is_rate_limited_but_force_is_not(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    d.sent.clear()
    d.state["settings"]["idle_color"] = 5  # changed behind the helper's back
    q.tick()
    assert d.sent == []  # within TICK_SECONDS of the last check
    q.tick(force=True)
    assert d.sent == ["SET idle_color 0"]


def test_tick_repeats_an_unanswered_set_only_after_the_backoff(tmp_path, monkeypatch):
    class Deaf(FakeDaemon):
        def send_command(self, line):
            self.sent.append(line)  # the device never acts on it

    d = Deaf()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    assert d.sent == ["SET idle_color 0"]
    fake_now = [time.monotonic()]
    monkeypatch.setattr(night.time, "monotonic", lambda: fake_now[0])
    fake_now[0] += night.TICK_SECONDS + 1
    q.tick()
    assert d.sent == ["SET idle_color 0"]
    fake_now[0] += night.RESEND_SECONDS
    q.tick()
    assert d.sent == ["SET idle_color 0", "SET idle_color 0"]


def test_tick_waits_for_a_connected_device(tmp_path):
    d = FakeDaemon(connected=False)
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    assert d.sent == []
    d.state["connected"] = True
    q.tick(force=True)
    assert d.sent == ["SET idle_color 0"]


def test_route_idle_setting_with_quiet_hours_off_goes_straight_to_the_device(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    assert q.route_idle_setting("idle_color", 5) is True
    assert d.sent == ["SET idle_color 5"]
    assert q.snapshot()["day"]["idle_color"] == 3  # not the helper's to keep yet


def test_route_idle_setting_by_day_updates_device_and_day_choice(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(12)
    q.update({"enabled": True})
    d.sent.clear()
    assert q.route_idle_setting("idle_color", 2) is True
    assert d.sent == ["SET idle_color 2"]
    assert q.snapshot()["day"]["idle_color"] == 2


def test_route_idle_setting_at_night_is_kept_for_the_morning(tmp_path):
    d = FakeDaemon()
    q = night.QuietHours(d, tmp_path / "night.json")
    q.clock = at(23)
    q.update({"enabled": True})
    d.sent.clear()
    assert q.route_idle_setting("idle_color", 2) is False
    assert d.sent == []
    assert q.snapshot()["day"]["idle_color"] == 2
    q.clock = at(8)
    q.tick(force=True)
    assert d.sent == ["SET idle_color 2"]
