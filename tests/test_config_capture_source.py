"""Capture source persistence tests (requirement: capture mode config persisted)."""

from config import AppConfig


def test_capture_source_defaults():
    cfg = AppConfig(path="unused.json")
    assert cfg.capture["source"] == "window"
    assert cfg.capture["monitor"] == 0


def test_capture_source_roundtrip(tmp_path):
    path = str(tmp_path / "config" / "freelossless.json")
    cfg = AppConfig(path=path)
    cfg.capture["source"] = "fullscreen"
    cfg.capture["monitor"] = 1
    cfg.save()

    loaded = AppConfig.load(path)
    assert loaded.capture["source"] == "fullscreen"
    assert loaded.capture["monitor"] == 1


def test_capture_source_aliases_sanitized(tmp_path):
    path = str(tmp_path / "cfg.json")
    cfg = AppConfig(path=path, data={"capture": {"source": "Full Screen", "monitor": 3}})
    assert cfg.capture["source"] == "fullscreen"
    assert cfg.capture["monitor"] == 3
    cfg.save()

    # Invalid values fall back to safe defaults
    cfg2 = AppConfig(path=path, data={"capture": {"source": "banana", "monitor": "NaN"}})
    assert cfg2.capture["source"] == "window"
    assert cfg2.capture["monitor"] == 0


def test_capture_monitor_clamped():
    cfg = AppConfig(path="unused.json", data={"capture": {"monitor": 99}})
    assert cfg.capture["monitor"] == 15
    cfg = AppConfig(path="unused.json", data={"capture": {"monitor": -4}})
    assert cfg.capture["monitor"] == 0
