"""Pipeline stage-chain tests: all four combinations + fallback (requirement 4,
12 & 18).  Uses injected fakes so they run without GPU / Windows / torch.
"""

import numpy as np

from neural.base import DisabledRenderer, NeuralRenderer, RendererStatus, STATE_READY
from pipeline import FramePipeline


class FakeEngine:
    """Stand-in for RIFEEngine/RIFEONNXEngine."""

    def __init__(self):
        self.calls = 0

    def interpolate(self, a, b):
        self.calls += 1
        return ((a.astype(np.int16) + b.astype(np.int16)) // 2).astype(np.uint8)


class MarkerRenderer(NeuralRenderer):
    """Adds 1 to every pixel, marks frames it has seen."""

    name = "Marker"

    def __init__(self):
        self.calls = 0

    def initialize(self):
        return True

    def process(self, frame):
        self.calls += 1
        return np.minimum(frame.astype(np.int16) + 1, 255).astype(np.uint8)

    def shutdown(self):
        pass

    def status(self):
        return RendererStatus(state=STATE_READY, backend="marker")


def _frame(seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 200, size=(32, 48, 3), dtype=np.uint8)


def test_combo_dlss5_off_rife_off():
    engine = FakeEngine()
    renderer = DisabledRenderer()
    pipe = FramePipeline(engine=engine, renderer=renderer,
                         internal_res=(800, 600), fg_enabled=False)
    f1, f2 = _frame(1), _frame(2)
    out1 = pipe.process_frame(f1)
    out2 = pipe.process_frame(f2)
    assert engine.calls == 0
    assert len(out1) == 1 and len(out2) == 1
    assert np.array_equal(out1[0], f1)          # untouched
    assert np.array_equal(out2[0], f2)


def test_combo_dlss5_on_rife_off():
    engine = FakeEngine()
    renderer = MarkerRenderer()
    pipe = FramePipeline(engine=engine, renderer=renderer,
                         internal_res=(800, 600), fg_enabled=False)
    f1, f2 = _frame(1), _frame(2)
    out1 = pipe.process_frame(f1)
    out2 = pipe.process_frame(f2)
    assert engine.calls == 0
    assert renderer.calls == 2
    assert len(out1) == 1 and len(out2) == 1
    expected1 = np.minimum(f1.astype(np.int16) + 1, 255).astype(np.uint8)
    assert np.array_equal(out1[0], expected1)


def test_combo_dlss5_off_rife_on():
    engine = FakeEngine()
    renderer = DisabledRenderer()
    pipe = FramePipeline(engine=engine, renderer=renderer,
                         internal_res=(800, 600), fg_enabled=True)
    f1, f2 = _frame(1), _frame(2)
    out1 = pipe.process_frame(f1)   # first frame: no interpolation yet
    out2 = pipe.process_frame(f2)   # [interpolated, current]
    assert len(out1) == 1
    assert len(out2) == 2
    assert engine.calls == 1
    assert np.array_equal(out2[1], f2)          # real frame untouched
    mid = ((f1.astype(np.int16) + f2.astype(np.int16)) // 2).astype(np.uint8)
    assert np.array_equal(out2[0], mid)


def test_combo_dlss5_on_rife_on():
    """The requested headline pipeline: Capture -> DLSS5 -> RIFE -> Overlay."""
    engine = FakeEngine()
    renderer = MarkerRenderer()
    pipe = FramePipeline(engine=engine, renderer=renderer,
                         internal_res=(800, 600), fg_enabled=True)
    f1, f2 = _frame(1), _frame(2)
    out1 = pipe.process_frame(f1)
    out2 = pipe.process_frame(f2)
    assert engine.calls == 1
    assert renderer.calls == 2
    assert len(out2) == 2
    # RIFE ran on the *enhanced* frames.
    e1 = np.minimum(f1.astype(np.int16) + 1, 255).astype(np.uint8)
    e2 = np.minimum(f2.astype(np.int16) + 1, 255).astype(np.uint8)
    mid = ((e1.astype(np.int16) + e2.astype(np.int16)) // 2).astype(np.uint8)
    assert np.array_equal(out2[0], mid)
    assert np.array_equal(out2[1], e2)


def test_neural_stage_order_before_rife():
    """DLSS5 must see the raw frame; RIFE must see the enhanced one."""
    order = []

    class TrackingRenderer(MarkerRenderer):
        def process(self, frame):
            order.append("dlss5")
            return super().process(frame)

    class TrackingEngine(FakeEngine):
        def interpolate(self, a, b):
            order.append("rife")
            return super().interpolate(a, b)

    pipe = FramePipeline(engine=TrackingEngine(), renderer=TrackingRenderer(),
                         internal_res=(800, 600), fg_enabled=True)
    pipe.process_frame(_frame(1))
    pipe.process_frame(_frame(2))
    # frame1: dlss5; frame2: dlss5 -> then rife on the enhanced pair
    assert order == ["dlss5", "dlss5", "rife"]


def test_pipeline_survives_renderer_crash():
    """Requirement 12: a crashing neural stage disables itself, RIFE continues."""

    class CrashRenderer(MarkerRenderer):
        def __init__(self):
            super().__init__()
            self.n = 0

        def process(self, frame):
            self.n += 1
            if self.n > 1:
                raise RuntimeError("neural stage exploded")
            return super().process(frame)

    engine = FakeEngine()
    pipe = FramePipeline(engine=engine, renderer=CrashRenderer(),
                         internal_res=(800, 600), fg_enabled=True)
    out1 = pipe.process_frame(_frame(1))
    out2 = pipe.process_frame(_frame(2))  # crash here -> frame passes through
    out3 = pipe.process_frame(_frame(3))  # still flowing
    assert len(out1) == 1 and len(out2) == 2 and len(out3) == 2
    assert engine.calls == 2  # interpolation kept running


def test_interpolation_engine_crash_is_soft():
    class CrashEngine(FakeEngine):
        def interpolate(self, a, b):
            raise RuntimeError("rife crashed")

    renderer = DisabledRenderer()
    pipe = FramePipeline(engine=CrashEngine(), renderer=renderer,
                         internal_res=(800, 600), fg_enabled=True)
    pipe.process_frame(_frame(1))
    out = pipe.process_frame(_frame(2))
    assert len(out) == 2  # original frame still emitted


def test_internal_res_resize():
    renderer = DisabledRenderer()
    pipe = FramePipeline(engine=FakeEngine(), renderer=renderer,
                         internal_res=(16, 16), fg_enabled=False)
    out = pipe.process_frame(_frame())  # 32x48 frame -> 16x16
    assert out[0].shape[:2] == (16, 16)
