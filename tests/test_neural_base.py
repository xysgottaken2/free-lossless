"""NeuralRenderer abstraction tests (requirement 5 & 7)."""

import numpy as np
import pytest

from neural import create_renderer
from neural.base import (
    DisabledRenderer,
    NeuralRenderer,
    RendererStatus,
    STATE_DISABLED,
    STATE_READY,
)
from neural.runtime import RuntimeLocator, default_native_dir


class ExplodingLocator(RuntimeLocator):
    """The runtime must NEVER be probed when DLSS 5 is switched off."""

    def report(self):
        raise AssertionError("runtime must not be probed when dlss5 is disabled")


def test_disabled_renderer_passes_through():
    r = DisabledRenderer()
    assert r.initialize() is True
    frame = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    out = r.process(frame)
    assert out is frame
    st = r.status()
    assert st.state == STATE_DISABLED
    assert st.frames_processed == 1
    r.shutdown()  # must be safe


def test_disabled_renderer_never_touches_runtime():
    r = create_renderer(
        {"enabled": False},
        locator=ExplodingLocator(),
        bridge_loader=lambda *_: (_ for _ in ()).throw(AssertionError("no bridge")),
    )
    assert isinstance(r, DisabledRenderer)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert r.process(frame) is frame


def test_create_renderer_disabled_by_default():
    r = create_renderer({})
    assert isinstance(r, DisabledRenderer)


def test_status_summary():
    st = RendererStatus(state=STATE_READY)
    assert st.summary() == "Ready"
    st = RendererStatus(state="error", error="boom")
    assert st.summary() == "Error: boom"


def test_info_keys():
    r = DisabledRenderer()
    info = r.info()
    for key in ("backend", "resolution", "model", "preset", "passes"):
        assert key in info


def test_default_native_dir_exists_concept():
    # Must point at a `native` folder next to the app (portable layout).
    assert default_native_dir().endswith("native")
