"""DLSS 5 renderer behaviour without a usable NVIDIA runtime.

Requirements covered:
  * #7  - the app must start and run Capture -> RIFE -> Overlay without the DLL
  * #8  - an invalid runtime must be detected (init verified, not assumed)
  * #12 - a mid-run DLSS 5 failure must fall back to RIFE, not kill the app
  * #18 - "DLSS5 sem DLL" and "DLSS5 com runtime inválido" test cases

These tests run on any machine (no GPU, no Windows, no NVIDIA DLLs).
"""

import numpy as np
import pytest

from neural import create_renderer
from neural.base import DisabledRenderer, STATE_ERROR, STATE_READY, STATE_UNAVAILABLE
from neural.bridge import BridgeError, FLNR_ERR_RUNTIME_INIT, FlNrStatus
from neural.dlss5 import DLSS5Renderer
from neural.runtime import RuntimeLocator


def _frame(h=32, w=48):
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def test_no_runtime_reports_unavailable_and_passes_through(tmp_path, capsys):
    """native/ is empty -> '[DLSS5] Runtime not found', frame untouched."""
    locator = RuntimeLocator(str(tmp_path))
    r = create_renderer({"enabled": True}, locator=locator)
    assert isinstance(r, DLSS5Renderer)
    assert r.status().state == STATE_UNAVAILABLE

    frame = _frame()
    out = r.process(frame)
    assert out is frame  # fail-soft pass-through

    captured = capsys.readouterr().out
    assert "[DLSS5] Runtime not found" in captured
    assert "[DLSS5] Neural Rendering disabled" in captured
    r.shutdown()  # safe twice
    r.shutdown()


def test_missing_runtime_does_not_load_bridge(tmp_path):
    """Without the runtime DLL the bridge must not even be touched."""
    locator = RuntimeLocator(str(tmp_path))

    def forbidden(_dir):
        raise AssertionError("bridge must not be loaded without the runtime")

    r = DLSS5Renderer({"enabled": True}, locator=locator, bridge_loader=forbidden)
    assert r.initialize() is False
    assert r.status().state == STATE_UNAVAILABLE


def test_invalid_runtime_detected_and_fallback(tmp_path):
    """A garbage nvngx_dlssnr.dll must be detected during init verification."""
    native = tmp_path / "native"
    native.mkdir()
    (native / "nvngx_dlssnr.dll").write_bytes(b"this is not a PE runtime")

    def broken_loader(_dir):
        raise BridgeError(FLNR_ERR_RUNTIME_INIT, "simulated Init_Ext failure 0xBAD00002")

    r = create_renderer(
        {"enabled": True},
        locator=RuntimeLocator(str(native)),
        bridge_loader=broken_loader,
    )
    st = r.status()
    assert st.state == STATE_UNAVAILABLE
    assert "Init_Ext failure" in st.error
    frame = _frame()
    assert r.process(frame) is frame


class FakeBridge:
    """Scriptable stand-in for freelossless-nvngx.dll."""

    def __init__(self, fail_process_after=None):
        self.fail_process_after = fail_process_after
        self.calls = 0
        self.inited = False
        self.shutdowns = 0

    def init(self, options, native_dir, log_dir):
        self.inited = True
        self.options = options
        return FlNrStatus()

    def process(self, frame):
        self.calls += 1
        if self.fail_process_after is not None and self.calls > self.fail_process_after:
            raise BridgeError(-8, "simulated NGX EvaluateFeature crash")
        out = np.minimum(frame.astype(np.int16) + 1, 255).astype(np.uint8)
        return out, FlNrStatus()

    def status(self):
        st = FlNrStatus()
        st.backend = b"fake-bridge"
        st.last_ngx_result = 1
        return st

    def shutdown(self):
        self.shutdowns += 1


def _ready_renderer(tmp_path, bridge):
    native = tmp_path / "native"
    native.mkdir(exist_ok=True)
    (native / "nvngx_dlssnr.dll").write_bytes(b"x" * (11 * 1024 * 1024))  # big enough
    return DLSS5Renderer(
        {
            "enabled": True,
            "passes": 1,
            "preset": 1,
            "style": 1,
            "intensity": 0.35,
            "work_scale": 1.0,
            "temporal": 0,
        },
        locator=RuntimeLocator(str(native)),
        bridge_loader=lambda _dir: bridge,
        expected_size=(48, 32),
    )


def test_probe_success_reports_ready(tmp_path):
    bridge = FakeBridge()
    r = _ready_renderer(tmp_path, bridge)
    assert r.initialize() is True
    st = r.status()
    assert st.state == STATE_READY
    assert st.backend == "fake-bridge"
    assert "nvngx_dlssnr.dll" in st.model
    # probe frame + real frame
    frame = _frame()
    out = r.process(frame)
    assert out is not frame
    assert np.all(out == np.minimum(frame.astype(np.int16) + 1, 255))
    assert st.frames_processed == 0  # snapshot taken before
    assert r.status().frames_processed == 1


def test_midrun_failure_falls_back_and_keeps_flowing(tmp_path):
    """Requirement 12: DLSS5 error -> disable -> continue with RIFE."""
    bridge = FakeBridge(fail_process_after=3)  # probe + 2 frames OK, 3rd fails
    r = _ready_renderer(tmp_path, bridge)
    assert r.initialize() is True

    for _ in range(2):
        out = r.process(_frame())
        assert out is not None

    frame3 = _frame()
    out3 = r.process(frame3)  # this call fails inside the bridge
    assert out3 is frame3  # original frame flows onward
    st = r.status()
    assert st.state == STATE_ERROR
    assert "EvaluateFeature" in st.error or "simulated" in st.error

    # Subsequent frames keep passing through untouched (no crash).
    frame4 = _frame()
    assert r.process(frame4) is frame4
    assert bridge.shutdowns >= 1


def test_resolution_change_recreates_feature(tmp_path):
    bridge = FakeBridge()
    r = _ready_renderer(tmp_path, bridge)
    assert r.initialize() is True
    r.process(_frame(32, 48))
    r.process(_frame(64, 96))  # different size -> rebuild
    assert r.status().resolution == "96x64"


def test_disabled_state_never_probes(tmp_path):
    """Requirement 18: DLSS5 off -> no runtime load attempts."""
    called = []

    def loader(_dir):
        called.append(1)
        return FakeBridge()

    r = create_renderer(
        {"enabled": False},
        locator=RuntimeLocator(str(tmp_path)),
        bridge_loader=loader,
    )
    assert isinstance(r, DisabledRenderer)
    r.process(_frame())
    assert called == []
