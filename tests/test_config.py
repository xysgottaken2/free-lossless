"""Configuration persistence tests (requirement 10 & 18)."""

import json
import os

from config import AppConfig, DEFAULT_CONFIG


def test_defaults(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "cfg.json"))
    assert cfg.dlss5["enabled"] is False
    assert cfg.rife["enabled"] is True
    assert cfg.dlss5["passes"] == 1
    assert cfg.dlss5["preset"] == DEFAULT_CONFIG["dlss5"]["preset"]


def test_roundtrip_save_load(tmp_path):
    path = str(tmp_path / "config" / "freelossless.json")
    cfg = AppConfig(path=path)
    cfg.dlss5["enabled"] = True
    cfg.dlss5["preset"] = 2
    cfg.dlss5["passes"] = 2
    cfg.dlss5["style"] = 3
    cfg.dlss5["intensity"] = 0.25
    cfg.rife["enabled"] = False
    cfg.save()

    loaded = AppConfig.load(path)
    assert loaded.dlss5["enabled"] is True
    assert loaded.dlss5["preset"] == 2
    assert loaded.dlss5["passes"] == 2
    assert loaded.dlss5["style"] == 3
    assert abs(loaded.dlss5["intensity"] - 0.25) < 1e-9
    assert loaded.rife["enabled"] is False


def test_missing_file_uses_defaults(tmp_path):
    cfg = AppConfig.load(str(tmp_path / "does_not_exist.json"))
    assert cfg.dlss5["enabled"] is False
    assert cfg.rife["enabled"] is True


def test_corrupt_file_uses_defaults(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    cfg = AppConfig.load(str(path))
    assert cfg.dlss5["enabled"] is False


def test_values_are_clamped(tmp_path):
    path = str(tmp_path / "cfg.json")
    cfg = AppConfig(path=path)
    cfg.data["dlss5"]["passes"] = 99
    cfg.data["dlss5"]["style"] = 42
    cfg.data["dlss5"]["intensity"] = 7.5
    cfg.data["dlss5"]["work_scale"] = 0.01
    cfg.sanitize()
    assert cfg.dlss5["passes"] == 2
    assert cfg.dlss5["style"] == 6
    assert cfg.dlss5["intensity"] == 1.0
    assert cfg.dlss5["work_scale"] == 0.25


def test_bad_types_fall_back_to_defaults():
    cfg = AppConfig(data={"dlss5": {"intensity": "not-a-number", "passes": None}})
    cfg.sanitize()
    assert cfg.dlss5["intensity"] == DEFAULT_CONFIG["dlss5"]["intensity"]
    assert cfg.dlss5["passes"] == DEFAULT_CONFIG["dlss5"]["passes"]


def test_unknown_keys_are_preserved(tmp_path):
    path = str(tmp_path / "cfg.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"dlss5": {"future_option": 123}, "future_section": {"a": 1}}, fh)
    cfg = AppConfig.load(path)
    assert cfg.data["dlss5"]["future_option"] == 123
    assert cfg.data["future_section"]["a"] == 1
    cfg.save()
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw["dlss5"]["future_option"] == 123


def test_dlss5_options_copy_is_isolated():
    cfg = AppConfig()
    opts = cfg.dlss5_options()
    opts["enabled"] = True
    assert cfg.dlss5["enabled"] is False
