"""Tk UI smoke tests: Start/Stop button, capture modes, DLSS 5 optional.

These need a real Tk display: they run on Windows and under ``xvfb-run`` on
Linux CI; on machines without tkinter/display they are skipped.
"""

import os

import pytest

# FREE_LOSSLESS_REQUIRE_TK=1 (set in CI) turns "no Tk" from a skip into a
# failure so the UI smoke tests can never be silently skipped there.
if os.environ.get("FREE_LOSSLESS_REQUIRE_TK") == "1":
    import tkinter as tk
else:
    tk = pytest.importorskip("tkinter")

from app_controller import (  # noqa: E402
    BUTTON_START,
    BUTTON_STOP,
    STATUS_RUNNING,
    STATUS_STOPPED,
    AppController,
)


@pytest.fixture
def ui(tmp_path):
    try:
        from config import AppConfig
        import ui as ui_module
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ui module unavailable: {exc}")

    cfg = AppConfig(path=str(tmp_path / "freelossless.json"))
    try:
        widget = ui_module.GameSelectorUI(app_config=cfg)
    except tk.TclError as exc:  # no display
        if os.environ.get("FREE_LOSSLESS_REQUIRE_TK") == "1":
            raise
        pytest.skip(f"no Tk display: {exc}")
    yield widget
    try:
        widget.destroy()
    except Exception:
        pass


class FakeHost:
    def __init__(self):
        self.started = None
        self.stop_requests = 0

    def start_pipeline(self, selection):
        self.started = selection
        return True

    def request_stop(self):
        self.stop_requests += 1


def test_start_button_exists_with_stop_variant(ui):
    assert str(ui.start_button.cget("text")) == BUTTON_START
    assert "Stopped" in str(ui.status_label.cget("text"))


def test_start_stop_toggle_runs_and_stops_pipeline(ui):
    host = FakeHost()
    controller = AppController(host=host, ui=ui)
    ui.bind_controller(controller)

    # Full Screen mode: no window selection needed
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()

    ui.start_button.invoke()

    assert host.started is not None
    assert host.started["source"] == "fullscreen"
    assert host.started["monitor"] >= 0
    # Back to Start / Stopped after the (synchronous) run
    assert str(ui.start_button.cget("text")) == BUTTON_START
    assert str(ui.status_label.cget("text")) == STATUS_STOPPED


def test_button_shows_stop_while_running(ui):
    host = FakeHost()
    controller = AppController(host=host, ui=ui)
    ui.bind_controller(controller)

    ui.source_combo.set("Full Screen")
    ui._on_source_changed()

    seen = {}

    class ObservingHost(FakeHost):
        def start_pipeline(self, selection):
            seen["button"] = str(ui.start_button.cget("text"))
            seen["status"] = str(ui.status_label.cget("text"))
            super().start_pipeline(selection)

    controller.host = ObservingHost()
    ui.start_button.invoke()

    assert seen["button"] == BUTTON_STOP
    assert seen["status"] == STATUS_RUNNING


def test_fullscreen_mode_shows_monitor_picker(ui):
    assert ui.is_fullscreen() is False
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()
    assert ui.is_fullscreen() is True
    # Monitor combo is managed (packed), window tree frame is not
    assert ui.monitor_combo.winfo_manager() != ""
    assert ui.window_frame.winfo_manager() == ""

    ui.source_combo.set("Window")
    ui._on_source_changed()
    assert ui.window_frame.winfo_manager() != ""


def test_window_mode_requires_selection(ui):
    assert ui.collect_selection() is None

    ui.tree.insert("", "end", values=("My Game", "game.exe"), iid="12345")
    ui.tree.selection_set("12345")
    selection = ui.collect_selection()
    assert selection is not None
    assert selection["source"] == "window"
    assert selection["hwnd"] == 12345
    assert selection["title"] == "My Game"


def test_fullscreen_selection_needs_no_window(ui):
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()
    selection = ui.collect_selection()
    assert selection is not None
    assert selection["source"] == "fullscreen"
    assert "hwnd" not in selection
    assert selection["monitor"] >= 0


def test_capture_source_is_persisted(ui):
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()
    assert ui.app_config.capture["source"] == "fullscreen"

    ui.source_combo.set("Window")
    ui._on_source_changed()
    assert ui.app_config.capture["source"] == "window"


def test_dlss5_is_optional_and_disabled_by_default(ui):
    assert bool(ui.dlss5_var.get()) is False
    selection = ui.collect_selection()
    # (window mode without selection returns None; switch to fullscreen)
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()
    selection = ui.collect_selection()
    assert selection["dlss5_enabled"] is False
    # The panel exists and exposes the confirmed runtime controls
    assert ui.dlss5_intensity_var is not None
    assert ui.dlss5_style_combo is not None
    assert ui.dlss5_passes_combo is not None
    assert ui.dlss5_work_scale_combo is not None
    assert ui.dlss5_auto_mask_var is not None


def test_window_mode_settings_keys_match_pipeline(ui):
    """The selection dict must keep the keys the pipeline has always used."""
    ui.source_combo.set("Full Screen")
    ui._on_source_changed()
    selection = ui.collect_selection()
    for key in ("mode", "fps", "scale", "algo", "sharpness", "fg_enabled",
                "engine_type", "ultra_smooth", "performance_mode", "low_latency",
                "dlss5_enabled", "dlss5_intensity", "dlss5_style", "dlss5_passes",
                "dlss5_work_scale", "dlss5_auto_mask"):
        assert key in selection, key
