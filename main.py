import ctypes
import gc
import multiprocessing
import os
import re
import threading
import time
import traceback
from queue import Empty, Full, Queue

try:  # Tk is only needed for the error dialog, and it is missing on some Linux boxes.
    from tkinter import messagebox
except ImportError:  # pragma: no cover - the Windows build always ships Tk
    messagebox = None

import diagnostics
import i18n
import ort_providers
from settings import (DEFAULT_HOTKEYS, HOTKEY_SETTING_KEYS, MULTIPLIER_MAX,
                      MULTIPLIER_MIN, MULTIPLIER_STEP, SettingsStore)
from splash import run_splash

# The heavy modules (OpenCV, numpy, pygame, DXCAM, pywin32) take seconds to import
# in the frozen build, so they are loaded by load_runtime() right after the splash
# appears. Everything below reads them through these module globals.
cv2 = np = pygame = None
ScreenCapture = None
RIFEEngine = RIFEONNXEngine = None
GameSelectorUI = None
get_source_rect = get_source_monitor_rect = None
AMDFilters = NvidiaAIUpscaler = None
EffectChain = None
create_display = D3D11 = None
win32gui = win32con = win32api = None


# Windows refuses to map a large DLL when the system commit limit is reached, with
# "the paging file is too small for this operation to complete". It happens with a
# browser full of tabs open, a pagefile that a tuning guide disabled, or simply a small
# machine — and it is usually gone a moment later. The import is retried before the app
# gives up, and giving up means explaining the failure instead of a raw traceback: the
# windowed build has no console, so a traceback there is invisible.
STARTUP_IMPORT_ATTEMPTS = 3
STARTUP_RETRY_SECONDS = 1.5


class RuntimeLoadError(RuntimeError):
    """A module the overlay needs could not be imported after every attempt."""

    def __init__(self, module_name, error):
        super().__init__(f"{module_name}: {error}")
        self.module_name = module_name
        self.error = error


def _failing_module(error):
    """Best-effort name of the module an ImportError came from."""
    name = getattr(error, "name", None)
    if name:
        return str(name)
    match = re.search(r"importing ([A-Za-z_][\w.]*)", str(error))
    return match.group(1) if match else "?"


def runtime_loaded():
    return pygame is not None


def _import_runtime():
    """The heavy imports themselves, in one place so they can be retried."""
    global cv2, np, pygame, ScreenCapture, RIFEEngine, RIFEONNXEngine, GameSelectorUI
    global get_source_rect, get_source_monitor_rect, AMDFilters, NvidiaAIUpscaler, EffectChain
    global create_display, D3D11
    global win32gui, win32con, win32api
    import cv2 as cv2_module
    import numpy as numpy_module
    import pygame as pygame_module
    import win32api as win32api_module
    import win32con as win32con_module
    import win32gui as win32gui_module
    from capture import ScreenCapture as capture_class
    from effects import EffectChain as effect_chain_class
    from d3d_display import create_display as display_factory, D3D11 as d3d11_mode
    from engine import RIFEEngine as fast_engine, RIFEONNXEngine as ai_engine
    from filters import AMDFilters as amd_filters, NvidiaAIUpscaler as nvidia_upscaler
    from selector import (get_source_monitor_rect as monitor_rect_function,
                          get_source_rect as source_rect_function)
    from ui import GameSelectorUI as selector_ui
    cv2, np, pygame = cv2_module, numpy_module, pygame_module
    win32api, win32con, win32gui = win32api_module, win32con_module, win32gui_module
    ScreenCapture = capture_class
    RIFEEngine, RIFEONNXEngine = fast_engine, ai_engine
    AMDFilters, NvidiaAIUpscaler = amd_filters, nvidia_upscaler
    EffectChain = effect_chain_class
    create_display, D3D11 = display_factory, d3d11_mode
    get_source_rect, get_source_monitor_rect = source_rect_function, monitor_rect_function
    GameSelectorUI = selector_ui


def load_runtime():
    """Import the overlay dependencies, retrying a transient Windows failure.

    Calling it twice is harmless. Each attempt imports everything again from scratch:
    Python drops a module that failed to import, so a second try really does retry the
    DLL that Windows refused to map.
    """
    if runtime_loaded():
        return
    last_error = None
    for attempt in range(1, STARTUP_IMPORT_ATTEMPTS + 1):
        try:
            _import_runtime()
            if attempt > 1:
                diagnostics.write_now("início", f"carregado na tentativa {attempt}")
            return
        except ImportError as exc:
            last_error = exc
            gc.collect()
            if attempt < STARTUP_IMPORT_ATTEMPTS:
                diagnostics.write_now(
                    "início",
                    f"falha ao carregar {_failing_module(exc)} "
                    f"(tentativa {attempt}/{STARTUP_IMPORT_ATTEMPTS}): {exc}")
                time.sleep(STARTUP_RETRY_SECONDS)
    raise RuntimeLoadError(_failing_module(last_error), last_error) from last_error


# Window styles of the overlay. WS_EX_TRANSPARENT makes it click-through and
# WS_EX_NOACTIVATE keeps Windows from giving it focus (Win key, Alt+Tab and game
# launchers all re-activate windows), which is what used to turn the overlay into a
# window the user could grab and move.
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
# How often the window styles are re-applied while the overlay is running.
WINDOW_STYLE_REFRESH_SECONDS = 0.5

# Fallbacks keep the overlay usable if a saved hotkey is missing or invalid.
DEFAULT_HOTKEY_VK = {"stop": 0x7A, "fps": 0x79, "fsr": 0x78}
DEFAULT_HOTKEY_NAMES = {action: DEFAULT_HOTKEYS[f"hotkey_{action}"] for action in DEFAULT_HOTKEY_VK}


def hotkey_vk_code(name, fallback):
    """Map a configured key name such as ``F9`` to its Windows virtual-key code."""
    if isinstance(name, str):
        digits = name.strip().upper().lstrip("F")
        if digits.isdigit() and 1 <= int(digits) <= 12:
            return 0x6F + int(digits)
    return fallback


def capture_interval(target_fps, multiplier, unlimited=False):
    """Seconds between captures: FPS / multiplier, so generated frames fill the rest.

    With ``unlimited`` there is no schedule at all: the capture runs every time the
    source produces a new frame, and the multiplier is applied on top of that rate
    by the generator instead of being carved out of a fixed output rate.
    """
    if unlimited:
        return 0.0
    try:
        multiplier = max(1, int(multiplier or 1))
    except (TypeError, ValueError):
        multiplier = 2
    rate = (target_fps / multiplier) if target_fps and target_fps > 0 else (30.0 / multiplier)
    return 1.0 / rate if rate > 0 else 1.0


def display_interval(target_fps, unlimited=False):
    """Seconds between presented frames; ``0.0`` means "present every frame we have"."""
    if unlimited:
        return 0.0
    try:
        target_fps = int(target_fps)
    except (TypeError, ValueError):
        target_fps = 60
    return 1.0 / target_fps if target_fps > 0 else 0.0


# Nothing new arrived: how long the capture and the presentation loops wait before
# looking again. Small enough to catch the next real frame, long enough not to spin.
UNLIMITED_IDLE_SLEEP = 0.0005


# Generation may use at most this share of the capture interval; the rest is
# headroom for capture, queueing and display, which must never be starved.
GENERATION_BUDGET_RATIO = 0.9
# A filter that needs more than this many frame intervals cannot keep up with the
# overlay; it is dropped for the session instead of turning the image into a slideshow.
AI_UPSCALE_BUDGET_RATIO = 2.0
# An engine slower than this cannot generate frames for a real-time overlay.
SLOW_ENGINE_MS = 250.0


def affordable_timesteps(timesteps, budget_ms, inference_ms):
    """Keep the intermediate frames that fit in the time before the next capture.

    A generator that is slower than the capture rate must not queue stale frames:
    it is better to show only real frames (always fresh) than a slideshow of old
    interpolated ones. ``inference_ms`` is unknown at first, so everything fits.
    """
    if not timesteps:
        return []
    if inference_ms is None or inference_ms <= 0:
        return list(timesteps)
    count = int(budget_ms // inference_ms) if budget_ms > 0 else 0
    if count >= len(timesteps):
        return list(timesteps)
    if count <= 0:
        return []
    step = len(timesteps) / count
    picked = {timesteps[min(len(timesteps) - 1, int(index * step))] for index in range(count)}
    return sorted(picked)


# Explicit internal resolutions offered in the menu. "Auto" is the default and
# decides by algorithm (see internal_resolution_for).
# Auto keeps the sharp target while the generator can hold the rate. The interpolator
# costs time in proportion to the pixels it sees (measured on 2 cores: 18.6 ms at
# 800x600, 48 ms at 720p, 83 ms at 1080p), so when the measured generation rate falls
# below this fraction of what the requested multiplier needs, Auto steps the processing
# resolution down — one step per window, at most down the ladder — instead of letting
# the overlay judder. Explicit menu choices never adapt.
AUTO_RESOLUTION_STEPS = (1.0, 0.7, 0.49, 0.34)
AUTO_PROBE_SECONDS = 3.0
AUTO_PROBE_MIN_RATIO = 0.75

INTERNAL_RESOLUTION_TARGETS = {
    "Performance": (800, 600),
    "HD": (1280, 720),
    "Full HD": (1920, 1080),
}


def internal_resolution_for(source_size, display_size, algorithm="", choice="Auto",
                            performance_mode=False, auto_step=0):
    """The resolution the whole pipeline works at.

    Everything used to be capped at 800x600, so a 1080p overlay showed a 2.4x blow-up
    of a small image — the "144p" look. These rules keep at most one resampling step
    and none when the source already matches the display:

    * Auto + neural upscale: half the display, because the model doubles the frame;
    * Auto otherwise: the source size, capped at the display size;
    * explicit choices (Performance/HD/Full HD/Native) always win, but are still
      capped at the source: processing more pixels than the source has would be
      upscaling done twice.
    """
    source_w, source_h = max(1, int(source_size[0])), max(1, int(source_size[1]))
    display_w, display_h = max(1, int(display_size[0])), max(1, int(display_size[1]))
    doubled_by_ai = False
    if choice == "Native":
        target = (source_w, source_h)
    elif choice in INTERNAL_RESOLUTION_TARGETS:
        target = INTERNAL_RESOLUTION_TARGETS[choice]
    elif "AI" in str(algorithm):
        doubled_by_ai = True
        target = (max(2, display_w // 2), max(2, display_h // 2))
    else:
        target = (min(source_w, display_w), min(source_h, display_h))
    if performance_mode and choice == "Auto":
        target = (min(target[0], 1280), min(target[1], 720))
    # Fit that target inside the source **keeping the source's shape**: clamping each
    # axis on its own would squeeze one side of the image, and every filter after that
    # would work on a distorted frame.
    factor = min(1.0, target[0] / source_w, target[1] / source_h)
    width, height = max(1, round(source_w * factor)), max(1, round(source_h * factor))
    if choice == "Auto" and auto_step:
        step_scale = auto_resolution_scale(auto_step)
        if step_scale is not None:
            width, height = max(1, round(width * step_scale)), max(1, round(height * step_scale))
    if doubled_by_ai:
        # Even sides keep the model's 2x output pixel aligned with the display.
        width, height = max(2, width - width % 2), max(2, height - height % 2)
    return width, height


def auto_resolution_scale(step):
    """Linear size factor for an Auto step; None when the ladder has no step left."""
    if step < 0:
        return AUTO_RESOLUTION_STEPS[0]
    if step >= len(AUTO_RESOLUTION_STEPS):
        return None
    return AUTO_RESOLUTION_STEPS[step]


def internal_resolution_reason(choice, algorithm):
    """Why that resolution was picked, for the log."""
    if choice in INTERNAL_RESOLUTION_TARGETS or choice == "Native":
        return "escolhida no menu"
    if "AI" in str(algorithm):
        return "metade da tela: o modelo de IA dobra o quadro"
    if "FSR" in str(algorithm):
        return "nativa da fonte: o EASU faz o upscale"
    return "nativa da fonte: sem reamostragem"


def queue_capacity(queue):
    """How many items a queue accepts.

    ``queue.Queue`` exposes ``maxsize``, but ``multiprocessing.Queue`` keeps it in
    ``_maxsize``: reading ``.maxsize`` from a process queue crashes with
    ``AttributeError`` (it did, five seconds into every overlay session).
    """
    for attribute in ("maxsize", "_maxsize"):
        value = getattr(queue, attribute, None)
        if isinstance(value, int):
            return value
    return 0


def put_latest(target_queue, item):
    """Queue a frame for a real-time consumer, dropping the oldest when full.

    Waiting for space would add lag instead of dropping frames nobody will see.
    """
    try:
        target_queue.put_nowait(item)
        return True
    except Full:
        pass
    try:
        target_queue.get_nowait()
    except Empty:
        pass
    try:
        target_queue.put_nowait(item)
        return True
    except Full:
        return False


def queue_sizes(multiplier, low_latency=True):
    """Buffer sizes for the pipeline: generated frames arrive in bursts."""
    try:
        multiplier = max(1, int(multiplier or 2))
    except (TypeError, ValueError):
        multiplier = 2
    process_size = min(8, max(3, multiplier))
    display_size = min(30, max(3, multiplier)) if low_latency else min(45, max(15, multiplier * 2))
    return 2, process_size, display_size


def effective_capture_multiplier(fg_enabled, multiplier, unlimited=False):
    """Interpolation fills the gaps, so captures slow down by the multiplier.

    With generation disabled nothing fills those gaps, so the capture has to keep
    the full target rate or the overlay would run at a fraction of it. Unlimited is
    the same idea for the opposite reason: the capture takes every real frame (the
    game's own rate) and the generator adds the intermediates on top of it.
    """
    if unlimited or not fg_enabled:
        return 1
    try:
        return max(1, int(multiplier or 2))
    except (TypeError, ValueError):
        return 2


def interpolation_timesteps(multiplier):
    """Positions of the intermediate frames generated between two captured frames.

    ``multiplier`` of 2 doubles the source rate with one frame at the midpoint;
    larger values spread the intermediates evenly across the pair.
    """
    try:
        multiplier = int(multiplier)
    except (TypeError, ValueError):
        multiplier = 2
    multiplier = max(1, multiplier)
    return [index / multiplier for index in range(1, multiplier)]


HUD_COLORS = {
    "accent": (118, 149, 255),
    "on": (105, 221, 178),
    "off": (150, 162, 178),
    "mode": (240, 188, 120),
    "muted": (154, 170, 192),
    "panel": (9, 14, 24, 200),
    "border": (44, 60, 84),
}
HUD_PADDING = 12
HUD_GAP = 8
HUD_CHIP_PADDING = 16


def hud_chips(fsr_on, ai_on, ultra_smooth, live=False, generated_fps=None):
    """Status chips for the overlay panel, as (label, value, color key).

    ``live`` marks frames that came straight from the capture because the pipeline
    could not keep up, so the panel says where the image is coming from and how
    many frames per second the generator is actually delivering.
    """
    mode = i18n.translate("hud.smooth") if ultra_smooth else i18n.translate("hud.standard")
    source = i18n.translate("hud.live") if live else i18n.translate("hud.generated")
    if generated_fps is not None and (generated_fps >= 1 or not live):
        source = f"{source} {round(generated_fps)}/s"
    return [
        ("FSR", "ON" if fsr_on else "OFF", "on" if fsr_on else "off"),
        ("AI", "ON" if ai_on else "OFF", "on" if ai_on else "off"),
        (i18n.translate("hud.mode"), mode, "mode" if ultra_smooth else "off"),
        ("", source, "mode" if live else "on"),
    ]


def processing_subroutine(capture_queue, process_queue, engine_config, stop_event):
    """
    Standalone subroutine for multiprocessing.

    It generates the intermediate frames between two captures, but never more
    than the hardware can afford: when the engine is slower than the capture
    rate, generating anyway would only queue stale frames that the overlay has
    to throw away.
    """
    from engine import RIFEEngine, RIFEONNXEngine

    # Generation is best effort: it must never take CPU from the game or from the
    # overlay's display loop, which is the part the player actually looks at.
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass

    engine_type = engine_config.get("engine_type")
    ultra_smooth = engine_config.get("ultra_smooth", False)

    def build_engine(kind):
        created = RIFEONNXEngine() if kind == "AI (RIFE ONNX)" else RIFEEngine()
        if hasattr(created, "set_high_precision"):
            created.set_high_precision(ultra_smooth)
        return created

    def describe(created, kind):
        session = getattr(created, "session", None)
        if session is None:
            return kind, ""
        try:
            return kind, " · ".join(session.get_providers())
        except Exception:
            return kind, ""

    engine = build_engine(engine_type)
    used_engine, providers = describe(engine, engine_type)
    if engine_type == "AI (RIFE ONNX)" and getattr(engine, "session", None) is None:
        # No session means the model could not be loaded at all: generating with it
        # would silently return one of the captured frames.
        diagnostics.write_now("motor", "RIFE ONNX não iniciou (DirectML/CUDA indisponível?): "
                                       "usando o motor Fast (DIS Flow) nesta sessão")
        engine = build_engine("Fast (DIS Flow)")
        used_engine, providers = describe(engine, "Fast (DIS Flow)")
    diagnostics.write_now("motor", f"{used_engine} iniciado no worker (PID {os.getpid()}){f' [{providers}]' if providers else ''}")
    if engine_type == "AI (RIFE ONNX)" and "Fast" not in used_engine and providers and not any(
            name in providers for name in ("DmlExecutionProvider", "CUDAExecutionProvider")):
        diagnostics.write_now("motor", "RIFE está rodando na CPU; a geração de frames será lenta. "
                                       "Instale onnxruntime-directml ou use o motor Fast (DIS Flow).")

    fg_enabled = engine_config.get("fg_enabled", True)
    multiplier = max(1, int(engine_config.get("frame_multiplier", 2) or 2))
    requested = interpolation_timesteps(multiplier) if fg_enabled else []
    last_frame = None
    last_capture_time = None
    arrival_ms = 0.0      # smoothed interval between captures
    inference_ms = 0.0    # smoothed cost of one interpolation
    generated = 0
    dropped = 0
    skipped = 0
    report_time = time.perf_counter()
    slow_engine_checked = False

    print(f"Sub-process processing worker started (PID: {os.getpid()}, frame gen x{multiplier})")

    while not stop_event.is_set():
        try:
            # We use a small timeout to check the stop_event periodically
            current_frame = capture_queue.get(timeout=0.1)
        except Exception:
            continue
        try:
            now = time.perf_counter()
            if last_capture_time is not None:
                gap = (now - last_capture_time) * 1000.0
                arrival_ms = gap if arrival_ms <= 0 else arrival_ms * 0.8 + gap * 0.2
            last_capture_time = now

            # No resizing here: the capture worker is the single place that scales
            # frames down, and a stale copy of the limit in this process would shrink
            # frames back after the user resizes the source window.
            timesteps = affordable_timesteps(requested, arrival_ms * GENERATION_BUDGET_RATIO, inference_ms)
            if requested and last_frame is not None and not timesteps:
                skipped += 1

            if timesteps and last_frame is not None:
                index = 0
                while index < len(timesteps):
                    timestep = timesteps[index]
                    started = time.perf_counter()
                    generated_frame = engine.interpolate(last_frame, current_frame, timestep)
                    spent = (time.perf_counter() - started) * 1000.0
                    inference_ms = spent if inference_ms <= 0 else inference_ms * 0.8 + spent * 0.2
                    if not slow_engine_checked and spent >= SLOW_ENGINE_MS and engine_type == "AI (RIFE ONNX)":
                        slow_engine_checked = True
                        diagnostics.write_now("motor", f"{used_engine} levou {spent:.0f} ms por quadro "
                                                       f"(nenhuma GPU/DirectML disponível): trocando para o "
                                                       f"motor Fast (DIS Flow) nesta sessão")
                        engine = build_engine("Fast (DIS Flow)")
                        used_engine, providers = describe(engine, "Fast (DIS Flow)")
                        inference_ms = 0.0
                        # The remaining frames of this pair fit again with the faster engine.
                        timesteps = affordable_timesteps(requested, arrival_ms * GENERATION_BUDGET_RATIO,
                                                         inference_ms)
                        index = 0
                        continue
                    index += 1
                    if not put_latest(process_queue, generated_frame):
                        dropped += 1
                    generated += 1
            if not put_latest(process_queue, current_frame):
                dropped += 1
            last_frame = current_frame

            report_time_now = time.perf_counter()
            if report_time_now - report_time >= 5.0:
                elapsed = report_time_now - report_time
                rate = generated / elapsed
                average = inference_ms
                message = (f"{rate:5.1f} frames gerados/s · inferência {average:5.1f} ms · "
                           f"capturas a cada {arrival_ms:4.1f} ms · {dropped} descartados")
                if skipped:
                    message += f" · {skipped} pares sem interpolação (orçamento estourado)"
                print(f"[frame gen] {message}")
                diagnostics.write_now("geração", message)
                generated = dropped = skipped = 0
                report_time = report_time_now
        except Exception as exc:
            diagnostics.write_now("geração", f"erro no worker: {exc}")
            continue


class FrameGenerationApp:
    def __init__(self, target_fps=60):
        self.target_fps = target_fps
        # Unlimited: no output pacing — the capture follows the game and the overlay
        # presents every frame as soon as it is ready.
        self.unlimited_fps = False
        self.last_presented_frame = None
        self.capture = None
        self.engine = RIFEEngine()
        self.running = False
        self.target_source = None
        
        # Queues for pipeline (Use multiprocessing queues for inter-process communication)
        self.capture_queue = multiprocessing.Queue(maxsize=2)
        self.process_queue = multiprocessing.Queue(maxsize=3)
        self.display_queue = Queue(maxsize=5) # Lighter buffer for lower latency
        
        # Stats
        self.frame_count = 0
        self.start_time = 0
        self.current_fps = 0
        self.live_fallback = False
        # Newest capture, already prepared for the display, used while the
        # generator is behind so the overlay keeps the game's own frame rate.
        self.live_display_queue = Queue(maxsize=1)
        self.last_live_display = None
        self.live_publish_time = 0.0
        self.want_live_frames = False
        self.starving_since = None
        self.healthy_since = None
        self.generated_fps = 0.0
        self.dropped_generated = 0
        self.last_frame_generated = False
        # Cost of rendering live frames, and the budget it must fit (half a frame).
        self.live_render_ms = 0.0
        self.live_render_budget_ms = 0.0
        self.live_cost_logged = False
        # Last image shown, reused for a brief hiccup instead of swapping to the capture.
        self.last_shown_frame = None
        
        # Window & Performance management
        self.last_rect = None
        self.show_fps = True
        self.hotkey_cooldown = 0
        self.frame_multiplier = 2
        self.hotkeys = dict(DEFAULT_HOTKEY_VK)
        self.hotkey_names = dict(DEFAULT_HOTKEY_NAMES)
        self.scale_factor = 1.0
        self.upscale_algo = cv2.INTER_LINEAR
        self.sharpness = 0.3
        self.internal_res = (800, 600) # Default target resolution for processing
        self._auto_step = 0            # ladder position of the automatic resolution
        self._auto_probe_start = time.perf_counter()
        self._auto_probe_generated = 0
        self.display_dim = (1280, 720) # Actual output dimensions
        self.fsr_mode = False # Toggle for AMD CAS/EASU
        self.ai_mode = False # Toggle for NVIDIA AI SuperRes
        self.ai_upscaler = None
        # Master switch for the image chain: sharpening, AI/FSR upscaling. When it is
        # off the frames go to the display with a plain resize, so the user can see
        # the raw image and compare.
        self.filters_enabled = True
        # Filter preset applied by the overlay itself (effects.py).
        self.filter_chain = None
        # How the overlay presents: "GDI" (pygame software blit) or "D3D11", which gives
        # the process a Direct3D swapchain so ReShade can hook it.
        self.display_mode = "GDI"
        self.display_presenter = None

    def capture_worker(self):
        print("Capture worker started")
        last_frame = None
        unlimited = bool(getattr(self, "unlimited_fps", False))
        multiplier = effective_capture_multiplier(getattr(self, "fg_enabled", True),
                                                   getattr(self, "frame_multiplier", 2), unlimited)
        interval = capture_interval(self.target_fps, multiplier, unlimited)

        last_capture_time = time.perf_counter()

        try:
            while self.running:
                # Windows follow their HWND; displays use their current desktop bounds.
                if self.target_source:
                    try:
                        rect = get_source_rect(self.target_source)
                        self.capture.region = rect # Update region
                    except Exception as exc:
                        print(f"Lost capture source, stopping: {exc}")
                        self.running = False
                        break

                # Sleep until the next capture instead of polling every millisecond:
                # the wait is precise and the thread stays idle in between.
                wait = interval - (time.perf_counter() - last_capture_time)
                if wait > 0:
                    time.sleep(min(wait, interval))
                    continue
                now = time.perf_counter()

                last_capture_time = now
                rect = self.capture.region
                if rect[2] <= rect[0] or rect[3] <= rect[1]:
                    continue
                frame = self.capture.capture_frame()

                if frame is not None:
                    # Scale once, here: the worker processes and the fallback path both
                    # use this resolution, and fewer bytes cross the process pipe.
                    frame = self._prepare_frame(frame)

                    # Optimized duplicate check
                    is_duplicate = False
                    if last_frame is not None:
                        try:
                            # Slice check is very fast
                            if np.array_equal(frame[10:30:2, 10:30:2], last_frame[10:30:2, 10:30:2]):
                                if np.array_equal(frame[::30, ::30], last_frame[::30, ::30]):
                                    is_duplicate = True
                        except: pass

                    if not is_duplicate:
                        last_frame = frame
                        # Prepare a display-ready copy for the fallback path: while the
                        # generator is behind, LIVE frames must look like generated ones.
                        now_publish = time.perf_counter()
                        if self.want_live_frames or now_publish - self.live_publish_time >= 0.2:
                            self.live_publish_time = now_publish
                            self._publish_live_frame(frame)
                        put_latest(self.capture_queue, frame)
                    elif unlimited:
                        # Nothing new on screen: back off a fraction of a millisecond
                        # instead of re-capturing in a tight loop. A game running at
                        # 60 Hz is still picked up with the next refresh.
                        time.sleep(UNLIMITED_IDLE_SLEEP)
        finally:
            # Release DXGI/GDI resources on the same worker that used them.
            self.capture.stop_capture()


    def _prepare_frame(self, frame):
        """Downscale a captured frame to the processing resolution.

        INTER_AREA averages the pixels it drops; INTER_LINEAR samples them, which turns
        fine texture into noise — visibly so when the source is 1080p and the pipeline
        works at 800x600 (measured: 37 dB against the correct downscale, versus 138 dB
        with INTER_AREA).
        """
        max_w, max_h = self.internal_res
        height, width = frame.shape[:2]
        # Fit inside the target keeping the frame's shape: clamping the sides on their
        # own would squeeze the picture (a 1920x1200 window on a 1920x1080 target).
        scale = min(max_w / width, max_h / height)
        if scale < 1.0:
            frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
        return frame

    def _fit_display(self, frame):
        """Resize a frame to the display size, with the right filter for the direction."""
        if (frame.shape[1], frame.shape[0]) == self.display_dim:
            return frame
        shrinking = frame.shape[1] > self.display_dim[0] or frame.shape[0] > self.display_dim[1]
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
        return cv2.resize(frame, self.display_dim, interpolation=interpolation)

    def _publish_live_frame(self, frame):
        """Render a captured frame exactly like a generated one.

        Same filters, same upscale: a live frame has to be indistinguishable from a
        generated one, otherwise falling back to the capture shows up as flicker. An
        earlier version switched to a cheap render when the cost went over budget —
        and since the cost hovers around the budget, consecutive frames alternated
        between sharp and soft, which is exactly what the eye picks up as flicker.
        The cost is measured and written to the log instead.
        """
        started = time.perf_counter()
        try:
            display = self._render_for_display(frame)
        except Exception as exc:
            diagnostics.write_now("exibição", f"falha ao preparar frame ao vivo: {exc}")
            return
        spent = (time.perf_counter() - started) * 1000.0
        self.live_render_ms = (spent if self.live_render_ms <= 0
                               else self.live_render_ms * 0.8 + spent * 0.2)
        if not self.live_cost_logged and self.live_render_ms > self.live_render_budget_ms:
            self.live_cost_logged = True
            diagnostics.write_now("exibição", f"frames ao vivo custam {self.live_render_ms:.1f} ms "
                                              f"(meio intervalo de quadro é "
                                              f"{self.live_render_budget_ms:.1f} ms): o modo LIVE "
                                              f"entrega uma imagem por captura")
        put_latest(self.live_display_queue, display)

    def _newest_live_frame(self):
        """Newest prepared capture; repeats the previous one instead of showing nothing."""
        while True:
            try:
                self.last_live_display = self.live_display_queue.get_nowait()
            except Empty:
                return self.last_live_display

    def _take_generated_frame(self, min_buffer):
        """Newest generated frame, dropping any backlog: late frames are stale."""
        while self.display_queue.qsize() > max(1, min_buffer):
            try:
                self.display_queue.get_nowait()
                self.dropped_generated += 1
            except Empty:
                break
        if self.display_queue.qsize() < min_buffer:
            return None
        try:
            return self.display_queue.get_nowait()
        except Empty:
            return None

    def _pick_frame(self, now, min_buffer, stall_timeout, return_delay):
        """Show the newest frame available, from the generator or from the capture.

        The image source is sticky. It only changes to the capture after generation
        has been behind for a whole stall window, and it only comes back after
        generation has been healthy for a while. Before this, a single late frame
        swapped the image for exactly one frame — interpolated, real, interpolated —
        which the eye reads as flicker. A short hiccup now repeats the previous image
        instead, and both paths are rendered the same way, so even a swap is subtle.
        """
        generated = self._take_generated_frame(min_buffer)
        if generated is not None:
            self.starving_since = None
        else:
            self.healthy_since = None
            if self.starving_since is None:
                self.starving_since = now
            if not self.live_fallback and now - self.starving_since >= stall_timeout:
                self.live_fallback = True
                print("Frame generation cannot keep up: showing the live capture.")
                diagnostics.write_now("exibição", "geração não acompanha o ritmo; "
                                                  "exibindo a captura direta (LIVE)")
        if self.live_fallback and generated is not None:
            if self.healthy_since is None:
                self.healthy_since = now
            elif now - self.healthy_since >= return_delay:
                self.live_fallback = False
                self.healthy_since = None
                print("Frame generation is keeping up again.")
                diagnostics.write_now("exibição", "geração voltou a acompanhar o ritmo (FG)")

        self.want_live_frames = self.live_fallback
        from_generator = False
        if self.live_fallback:
            # Stay on the capture for the whole episode: alternating between the two
            # sources frame by frame is the flicker being removed here.
            frame = self._newest_live_frame()
        elif generated is not None:
            frame, from_generator = generated, True
        elif self.frame_count == 0 or self.last_shown_frame is None:
            # First frames: there is nothing to hold on to, use the capture.
            frame = self._newest_live_frame()
        else:
            # A brief hiccup: repeat the last image instead of changing its look.
            frame = self.last_shown_frame
        if frame is not None:
            self.last_shown_frame = frame
        self.last_frame_generated = from_generator
        return frame

    def _repeat_of_presented(self, frame):
        """True when the same image would go to the screen a second time.

        With a fixed output rate the overlay presents on a schedule, so repeating the
        held image is harmless. Unlimited presents on every new frame, and presenting
        the same picture again would only burn CPU and inflate the counter.
        """
        return bool(self.unlimited_fps) and frame is self.last_presented_frame

    PERIODIC_REPORT_SECONDS = 5.0

    def _log_periodic_status(self, loop_now, diagnostics_time):
        """Every few seconds: shown FPS, generation rate, queue occupancy, frame source.

        Cosmetic by nature — and it has already taken the overlay down once (a
        ``multiprocessing.Queue`` has no ``.maxsize``), so the whole thing sits behind a
        guard and the timestamp is always returned, logged or not.
        """
        if loop_now - diagnostics_time < self.PERIODIC_REPORT_SECONDS:
            return diagnostics_time
        try:
            source = "live" if self.live_fallback else "generated"
            queue_size = self.display_queue.qsize()
            print(f"[overlay] {self.current_fps:5.1f} FPS exibidos  ·  "
                  f"{self.generated_fps:5.1f} frames gerados/s  ·  fila {queue_size}  ·  "
                  f"{source}  ·  captura {self.frame_multiplier}x")
            diagnostics.write_now("exibição", f"{self.current_fps:5.1f} FPS exibidos · "
                                               f"{self.generated_fps:5.1f} gerados/s · "
                                               f"{self._queue_report(queue_size)} · "
                                               f"{source} · {self.dropped_generated} descartados")
        except Exception as exc:
            # Write directly: the report itself is what failed.
            try:
                diagnostics.write_now("exibição", f"relatório periódico falhou: {exc}")
            except Exception:
                pass
        return loop_now

    def _queue_report(self, display_size=None):
        """One line about queue occupancy, for the periodic diagnostics log."""
        if display_size is None:
            display_size = self.display_queue.qsize()
        return (f"filas captura {self.capture_queue.qsize()}/{queue_capacity(self.capture_queue)}"
                f" · pós {self.process_queue.qsize()}/{queue_capacity(self.process_queue)}"
                f" · exibição {display_size}/{queue_capacity(self.display_queue)}")

    def _set_internal_resolution(self, rect, auto_step=0):
        """Pick the processing resolution for this source and display, and log it."""
        source = (rect[2] - rect[0], rect[3] - rect[1])
        choice = self.target_source.get("internal_resolution", "Auto")
        algorithm = self.target_source.get("algo", "")
        previous = getattr(self, "internal_res", None)
        self.internal_res = internal_resolution_for(
            source, self.display_dim, algorithm, choice,
            bool(self.target_source.get("performance_mode")), auto_step)
        self._auto_step = auto_step
        self._auto_probe_start = time.perf_counter()
        self._auto_probe_generated = 0
        if self.internal_res != previous:
            reason = internal_resolution_reason(choice, algorithm)
            if auto_step and choice == "Auto":
                reason = f"{reason}, degrau automático {auto_step} para manter o ritmo"
            message = (f"resolução interna {self.internal_res[0]}x{self.internal_res[1]} de "
                       f"{source[0]}x{source[1]} para {self.display_dim[0]}x{self.display_dim[1]} "
                       f"({reason})")
            print(f"[imagem] {message}")
            diagnostics.write_now("imagem", message)
        return self.internal_res

    def _auto_adapt(self, now):
        """Drop one Auto step when the generator cannot hold the requested rate.

        Called once per measuring window. The rate it compares is the one the user
        actually sees (generated frames that made it to the screen), so a machine that
        cannot interpolate 1080p at 2x is corrected in the first seconds of the session
        instead of juddering forever. An explicit menu choice is never overridden.
        """
        if self.target_source.get("internal_resolution", "Auto") != "Auto":
            return False
        if not getattr(self, "fg_enabled", True) or self.frame_multiplier <= 1:
            return False
        step = getattr(self, "_auto_step", 0)
        if auto_resolution_scale(step + 1) is None:
            return False
        elapsed = now - getattr(self, "_auto_probe_start", now)
        if elapsed < AUTO_PROBE_SECONDS:
            return False
        # In unlimited mode there is no configured rate to hit: the reference is what
        # the overlay is actually showing. If the generator delivers less than its
        # share of that, it is the bottleneck — and lowering the processing resolution
        # is exactly what raises the number of frames the machine can produce.
        reference = self.current_fps if getattr(self, "unlimited_fps", False) else self.target_fps
        required = reference * (self.frame_multiplier - 1) / self.frame_multiplier
        achieved = getattr(self, "_auto_probe_generated", 0) / elapsed
        if achieved >= required * AUTO_PROBE_MIN_RATIO:
            self._auto_probe_start = now     # healthy: watch the next window
            self._auto_probe_generated = 0
            return False
        self._set_internal_resolution(self.capture.region, auto_step=step + 1)
        diagnostics.write_now(
            "imagem",
            f"geração {achieved:.0f}/{required:.0f} quadros/s: resolução interna reduzida "
            f"para {self.internal_res[0]}x{self.internal_res[1]} (Auto, degrau {step + 1})")
        return True

    def _measure_filter_chain(self):
        """Log what the chosen filter preset costs per frame.

        Filters are the user's choice, so a heavy preset is not disabled; the cost is
        measured and written down, together with a warning when it takes more than the
        frame budget, which is what a user would otherwise feel as stutter without
        knowing where it came from.
        """
        if self.filter_chain is None or not self.filter_chain.enabled:
            return
        width, height = self.internal_res
        sample = np.zeros((height, width, 3), dtype=np.uint8)
        try:
            self.filter_chain.apply(sample)
            started = time.perf_counter()
            self.filter_chain.apply(sample)
            cost_ms = (time.perf_counter() - started) * 1000.0
        except Exception as exc:
            diagnostics.write_now("filtros", f"preset {self.filter_chain.preset} falhou: {exc}")
            return
        budget_ms = 1000.0 / max(1, self.target_fps)
        message = (f"preset de filtros {self.filter_chain.preset}: {cost_ms:.1f} ms por quadro "
                   f"em {width}x{height} (orçamento {budget_ms:.1f} ms a {self.target_fps} FPS)")
        print(f"[filtros] {message}")
        diagnostics.write_now("filtros", message)
        if cost_ms > budget_ms:
            diagnostics.write_now("filtros", "o preset escolhido custa mais que um intervalo de "
                                            "quadro: use um preset mais leve ou abaixe os FPS de saída")

    def _prepare_ai_upscaler(self):
        """Measure the AI upscaler once and drop it when it cannot keep up.

        The same FSRCNN model costs a few milliseconds on a GPU and hundreds of
        milliseconds on the CPU. Rather than stalling every frame, the filter is
        turned off for the session with the reason written to the log (and to the
        console), and the normal sharpening/upscale path takes over.
        """
        if not (self.filters_enabled and self.ai_mode and self.ai_upscaler):
            return
        provider = ort_providers.describe(getattr(self.ai_upscaler, "session", None))
        if getattr(self.ai_upscaler, "session", None) is None:
            self.ai_mode = False
            message = "modelo de AI SuperRes indisponível: filtro desativado nesta sessão"
            print(f"AI upscaler disabled ({message})")
            diagnostics.write_now("ia", message)
            return
        width, height = self.internal_res
        sample = np.zeros((height, width, 3), dtype=np.uint8)
        try:
            self.ai_upscaler.upscale(sample)          # the first call also builds the GPU kernels
            started = time.perf_counter()
            self.ai_upscaler.upscale(sample)
            cost_ms = (time.perf_counter() - started) * 1000.0
        except Exception as exc:
            cost_ms = float("inf")
            diagnostics.write_now("ia", f"falha ao executar o upscaler: {exc}")
        limit_ms = max(AI_UPSCALE_BUDGET_RATIO * 1000.0 / max(1, self.target_fps), 20.0)
        if cost_ms > limit_ms:
            self.ai_mode = False
            message = (f"AI SuperRes levou {cost_ms:.0f} ms por quadro em {provider} "
                       f"(limite de {limit_ms:.0f} ms para {self.target_fps} FPS): "
                       f"filtro desativado nesta sessão")
            print(f"AI upscaler disabled ({message})")
            diagnostics.write_now("ia", message)
        else:
            message = f"AI SuperRes ativo: {cost_ms:.1f} ms por quadro em {provider}"
            print(message)
            diagnostics.write_now("ia", message)

    def _overlay_window_handle(self):
        """Win32 handle of the overlay window, for the click-through styles."""
        presenter = getattr(self, "display_presenter", None)
        if presenter is not None:
            handle = presenter.hwnd()
            if handle:
                return handle
        try:
            return pygame.display.get_wm_info()["window"]
        except Exception:
            return None

    def _present_overlay(self, screen):
        """Flip the overlay: the SDL renderer when opted in, pygame's blit otherwise."""
        presenter = getattr(self, "display_presenter", None)
        if presenter is None:
            pygame.display.flip()
            return
        presenter.present()

    def _open_overlay_display(self, size):
        """Open the overlay window in the configured mode, falling back to GDI.

        D3D11 exists so ReShade can attach to the overlay (it hooks Direct3D, not the
        GDI blits pygame does by default). If the machine cannot give us a D3D
        swapchain, the overlay still opens — in GDI, with the reason in the log.
        """
        title = i18n.translate("app.title")
        requested = getattr(self, "display_mode", "GDI")
        if requested == D3D11:
            try:
                canvas, presenter, _ = create_display(D3D11, title, size)
                message = (f"exibição: D3D11 via SDL ({presenter.driver}) · o ReShade instalado "
                           f"nesta pasta passa a valer para o overlay")
                print(f"[exibição] {message}")
                diagnostics.write_now("exibição", message)
                return canvas, presenter
            except Exception as exc:
                message = f"modo D3D11 indisponível ({exc}): caindo para GDI nesta sessão"
                print(f"[exibição] {message}")
                diagnostics.write_now("exibição", message)
        canvas, presenter, _ = create_display("GDI", title, size)
        return canvas, presenter

    def _apply_overlay_window_style(self, rect, size):
        """Make the overlay click-through, always on top and invisible to captures.

        Windows resets a window's extended styles whenever SDL recreates it, and it
        hands the window focus back when something like the Win key is pressed. Both
        cases used to leave the overlay grabbing the mouse, so the styles are applied
        again on every geometry change and periodically while it runs.
        """
        hwnd = self._overlay_window_handle()
        if not hwnd:
            if not getattr(self, "_window_handle_warned", False):
                self._window_handle_warned = True
                diagnostics.write_now("exibição", "não foi possível obter o handle da janela do "
                                                 "overlay: click-through e sempre-no-topo não "
                                                 "puderam ser aplicados")
            return
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass  # only available on Windows 10 2004 and newer
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            wanted = style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            if wanted != style:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, wanted)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, rect[0], rect[1], size[0], size[1],
                                  win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
        except Exception as exc:
            diagnostics.write_now("exibição", f"não foi possível ajustar a janela do overlay: {exc}")

    def _render_for_display(self, frame):
        """Sharpen at the processing resolution, then upscale once for the display.

        Sharpening before the upscale is the difference between a few milliseconds
        and tens of milliseconds per frame on a 1080p or larger display.
        """
        needs_upscale = (frame.shape[1], frame.shape[0]) != self.display_dim
        if not self.filters_enabled:
            return self._fit_display(frame)
        # External (ReShade style) filters first, at the internal resolution: the same
        # work at display resolution costs several times more per frame.
        if self.filter_chain is not None and self.filter_chain.enabled:
            frame = self.filter_chain.apply(frame)
        if self.ai_mode and self.ai_upscaler:
            frame = self.ai_upscaler.upscale(frame)
            frame = self._fit_display(frame)
        elif self.fsr_mode:
            if self.sharpness > 0:
                frame = AMDFilters.apply_cas(frame, self.sharpness)
            if needs_upscale:
                frame = AMDFilters.apply_easu(frame, self.display_dim)
        else:
            if self.sharpness > 0:
                frame = AMDFilters.apply_unsharp(frame, self.sharpness)
            if needs_upscale:
                frame = cv2.resize(frame, self.display_dim, interpolation=self.upscale_algo)
        return frame

    def post_processing_worker(self):
        """Prepare every generated frame for the display.

        The queue is waited on, not polled: a 20 ms poll added up to 20 ms of delay
        to every single frame, which is two and a half frame intervals at 120 FPS.
        """
        print("Post-processing worker started")
        while self.running:
            try:
                frame = self.process_queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                put_latest(self.display_queue, self._render_for_display(frame))
            except Exception as exc:
                print(f"Post-processing error: {exc}")
                diagnostics.write_now("exibição", f"erro no pós-processamento: {exc}")

    def select_game(self):
        ui = GameSelectorUI()
        self.target_source = ui.get_selection()
        if not self.target_source:
            return False
        
        # Resolve the selection before initializing GPU/capture resources.
        try:
            rect = get_source_rect(self.target_source)
            monitor_rect = get_source_monitor_rect(self.target_source)
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise ValueError(i18n.translate("msg.invalid_source"))
        except Exception as exc:
            if messagebox is not None:
                messagebox.showerror(i18n.translate("msg.source_unavailable"), str(exc))
            print(f"Source unavailable: {exc}")
            return False
        self.capture = ScreenCapture(
            region=rect, mode=self.target_source["mode"], desktop_coordinates=True,
        )
        self.target_fps = self.target_source["fps"]
        self.unlimited_fps = bool(self.target_source.get("unlimited_fps", False))
        
        # Scaling config
        scale_val = self.target_source["scale"]
        if scale_val == "Fullscreen":
            self.scale_factor = -1 # Special flag for fullscreen
        else:
            self.scale_factor = float(scale_val)
            
        algo_val = self.target_source["algo"]
        # Every session starts from a clean image configuration.
        self.fsr_mode = False
        self.ai_mode = False
        self.ai_upscaler = None
        if algo_val == "Bilinear": self.upscale_algo = cv2.INTER_LINEAR
        elif algo_val == "Bicubic": self.upscale_algo = cv2.INTER_CUBIC
        elif algo_val == "Lanczos": self.upscale_algo = cv2.INTER_LANCZOS4
        elif "FSR" in algo_val:
            self.fsr_mode = True
        elif "AI" in algo_val:
            self.ai_mode = True

        self.fg_enabled = self.target_source.get("fg_enabled", True)

        self.filters_enabled = self.target_source.get("filters_enabled", True)
        self.sharpness = self.target_source["sharpness"] / 100.0 * 2.0 # Scale 0-100 to 0.0-2.0
        if not self.filters_enabled:
            # No image processing at all: no sharpening, FSR or neural upscale. The
            # model is not even loaded, which also saves the seconds it takes to
            # initialise a session.
            self.fsr_mode = False
            self.ai_mode = False
            self.sharpness = 0.0
        elif self.ai_mode:
            self.ai_upscaler = NvidiaAIUpscaler()

        self.filter_chain = EffectChain(self.target_source.get("filter_preset", "Off"))
        self.display_mode = self.target_source.get("display_mode", "GDI")
        self.display_presenter = None
        self.ultra_smooth = self.target_source.get("ultra_smooth", False)
        if self.target_source.get("engine_type") == "AI (RIFE ONNX)":
            self.engine = RIFEONNXEngine()
        else:
            self.engine = RIFEEngine()
            
        self.engine.set_high_precision(self.ultra_smooth) if hasattr(self.engine, 'set_high_precision') else None

        # Frame generation multiplier: how many output frames each captured pair becomes.
        multiplier = self.target_source.get("frame_multiplier", 2)
        if (type(multiplier) is not int or not MULTIPLIER_MIN <= multiplier <= MULTIPLIER_MAX
                or multiplier % MULTIPLIER_STEP):
            multiplier = 2
        self.frame_multiplier = multiplier
        self.show_fps = self.target_source.get("show_fps", True)

        # Hotkeys are configurable; fall back to F11/F10/F9 for missing values.
        self.hotkeys = {}
        self.hotkey_names = {}
        for setting_key in HOTKEY_SETTING_KEYS:
            action = setting_key.removeprefix("hotkey_")
            name = self.target_source.get(setting_key)
            if not isinstance(name, str) or not name:
                name = DEFAULT_HOTKEY_NAMES[action]
            self.hotkey_names[action] = name
            self.hotkeys[action] = hotkey_vk_code(name, DEFAULT_HOTKEY_VK[action])

        # Adaptive Buffer based on latency selection
        self.low_latency = self.target_source.get("low_latency", True)

        # Queues sized so a burst of generated frames has somewhere to wait.
        capture_size, process_size, display_size = queue_sizes(multiplier, self.low_latency)
        self.capture_queue = multiprocessing.Queue(maxsize=capture_size)
        self.process_queue = multiprocessing.Queue(maxsize=process_size)
        self.display_queue = Queue(maxsize=display_size)

        # Initial display dimensions
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if self.scale_factor == -1:
            self.display_dim = (monitor_rect[2] - monitor_rect[0], monitor_rect[3] - monitor_rect[1])
        else:
            self.display_dim = (int(w * self.scale_factor), int(h * self.scale_factor))

        self._set_internal_resolution(rect)

        rate_label = "unlimited" if self.unlimited_fps else f"{self.target_fps} FPS"
        print(f"Targeting: {self.target_source['title']} | Mode: {self.target_source['mode']} | "
              f"FPS: {rate_label} | Scale: {scale_val} | Frame gen: x{multiplier}")
        print(f"Press {self.hotkey_names['stop']} to stop, {self.hotkey_names['fps']} to toggle FPS, "
              f"{self.hotkey_names['fsr']} to toggle FSR.")
        return True

    def _hud_chip_texts(self, small_font, show_rate):
        chips = []
        for label, value, state in hud_chips(self.fsr_mode, self.ai_mode, self.ultra_smooth,
                                             live=self.live_fallback,
                                             generated_fps=self.generated_fps if show_rate else None):
            chips.append((HUD_COLORS[state], small_font.render(f"{label} {value}".strip(), True,
                                                              HUD_COLORS[state])))
        return chips

    def _hud_parts(self, font, small_font, max_width=None):
        """Render the panel once per status change, not once per displayed frame."""
        key = (round(self.current_fps), self.fsr_mode, self.ai_mode, self.ultra_smooth,
               self.live_fallback, round(self.generated_fps), i18n.get_language(), max_width)
        cached = getattr(self, "_hud_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        fps_value = font.render(f"{round(self.current_fps)}", True, HUD_COLORS["accent"])
        fps_label = small_font.render("FPS", True, HUD_COLORS["muted"])
        hint = small_font.render(f"{self.hotkey_names['stop']}  {i18n.translate('hud.menu')}",
                                 True, HUD_COLORS["muted"])
        chips = self._hud_chip_texts(small_font, show_rate=True)
        if max_width is not None:
            # Small windows: drop the generation rate before the panel overflows.
            widest = max(sum(text.get_width() + HUD_CHIP_PADDING for _, text in chips)
                         + HUD_GAP * max(0, len(chips) - 1),
                         fps_value.get_width() + HUD_GAP + fps_label.get_width(),
                         hint.get_width())
            if widest + HUD_PADDING * 2 > max_width:
                chips = self._hud_chip_texts(small_font, show_rate=False)

        chip_widths = [text.get_width() + HUD_CHIP_PADDING for _, text in chips]
        chip_height = max([text.get_height() for _, text in chips] + [0]) + HUD_GAP
        chip_backgrounds = []
        for (color, _), width in zip(chips, chip_widths):
            background = pygame.Surface((width, chip_height), pygame.SRCALPHA)
            background.fill((*color, 40))
            chip_backgrounds.append(background)
        fps_row = fps_value.get_width() + HUD_GAP + fps_label.get_width()
        chip_row = sum(chip_widths) + HUD_GAP * max(0, len(chips) - 1)
        content_width = max(fps_row, chip_row, hint.get_width())
        content_height = fps_value.get_height() + HUD_GAP + chip_height + HUD_GAP + hint.get_height()
        panel = pygame.Surface((content_width + HUD_PADDING * 2, content_height + HUD_PADDING * 2),
                               pygame.SRCALPHA)
        panel.fill(HUD_COLORS["panel"])
        parts = (panel, fps_value, fps_label, hint, chips, chip_widths, chip_height, chip_backgrounds)
        self._hud_cache = (key, parts)
        return parts

    def _draw_hud(self, screen, font, small_font):
        """Rounded translucent status panel: FPS, state chips and the F11 hint."""
        (panel, fps_value, fps_label, hint,
         chips, chip_widths, chip_height, chip_backgrounds) = self._hud_parts(
            font, small_font, max_width=max(0, screen.get_width() - 32))
        panel_width, panel_height = panel.get_width(), panel.get_height()
        screen.blit(panel, (16, 16))
        pygame.draw.rect(screen, HUD_COLORS["border"], (16, 16, panel_width, panel_height),
                         width=1, border_radius=12)

        x = 16 + HUD_PADDING
        y = 16 + HUD_PADDING
        screen.blit(fps_value, (x, y))
        screen.blit(fps_label, (x + fps_value.get_width() + HUD_GAP,
                                y + fps_value.get_height() - fps_label.get_height()))
        y += fps_value.get_height() + HUD_GAP
        for (chip_color, text), width, background in zip(chips, chip_widths, chip_backgrounds):
            screen.blit(background, (x, y))
            pygame.draw.rect(screen, chip_color, (x, y, width, chip_height), width=1, border_radius=8)
            screen.blit(text, (x + HUD_CHIP_PADDING // 2, y + (chip_height - text.get_height()) // 2))
            x += width + HUD_GAP
        y += chip_height + HUD_GAP
        screen.blit(hint, (16 + HUD_PADDING, y))

    def run(self):
        if not self.select_game():
            return False

        pygame.init()
        rect = self.capture.region
        
        # Borderless fullscreen on the source's monitor (including negative origins).
        # Exclusive pygame.FULLSCREEN would default to the primary display.
        d_w, d_h = self.display_dim
        overlay_rect = get_source_monitor_rect(self.target_source) if self.scale_factor == -1 else rect

        if d_w <= 0 or d_h <= 0:
            print("Invalid window dimensions.")
            return True

        # Setup Borderless Window
        screen, self.display_presenter = self._open_overlay_display((d_w, d_h))
        
        # FPS Font
        pygame.font.init()
        font = pygame.font.SysFont("Arial", 24, bold=True)
        small_font = pygame.font.SysFont("Arial", 18, bold=True)
        
        # Click-through, always on top on the source's monitor, and excluded from
        # screen capture so the overlay can never capture itself.
        self._apply_overlay_window_style(overlay_rect, (d_w, d_h))
        self.last_rect = rect

        # Increase process priority for better smoothness
        try:
            import psutil
            p = psutil.Process()
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        except: pass

        self.running = True
        self.start_time = time.time()
        
        # Prepare config for sub-process
        engine_config = {
            "engine_type": self.target_source.get("engine_type"),
            "ultra_smooth": self.ultra_smooth,
            "fg_enabled": self.fg_enabled,
            "frame_multiplier": self.frame_multiplier,
            "internal_res": self.internal_res
        }
        
        self.stop_event = multiprocessing.Event()
        
        t_cap = threading.Thread(target=self.capture_worker, daemon=True)
        # Use multiprocessing for the heavy lifter
        p_proc = multiprocessing.Process(
            target=processing_subroutine, 
            args=(self.capture_queue, self.process_queue, engine_config, self.stop_event),
            daemon=True
        )
        t_post = threading.Thread(target=self.post_processing_worker, daemon=True)
        
        self._measure_filter_chain()
        self._prepare_ai_upscaler()

        t_cap.start()
        p_proc.start()
        t_post.start()
        
        unlimited = bool(getattr(self, "unlimited_fps", False))
        frame_interval = display_interval(self.target_fps, unlimited)
        # The reference interval still comes from the configured rate: in unlimited
        # mode it is what tells the overlay how long a "short" hiccup lasts.
        reference_interval = display_interval(self.target_fps)
        # Live frames are rendered in the capture thread: half a frame interval is what
        # it may spend without holding the captures back.
        self.live_render_budget_ms = max(1.0, reference_interval * 1000.0 * 0.5)
        # The generator needs to miss a whole frame before LIVE frames take over, and
        # it has to prove it recovered before generated frames come back. Without the
        # second delay the two sources alternate every frame, which the eye reads as
        # flicker.
        stall_timeout = max(reference_interval * 2, 0.03)
        return_delay = max(stall_timeout * 3, 0.3)
        last_display_time = time.perf_counter()
        fps_window_start = last_display_time
        fps_window_frames = 0
        generated_window = 0
        diagnostics_time = last_display_time
        last_style_check = last_display_time
        self.sync_counter = 0
        self.last_presented_frame = None
        diagnostics.reset()
        diagnostics.write_now("início", f"overlay {self.display_dim[0]}x{self.display_dim[1]} · "
                                        f"interno {self.internal_res[0]}x{self.internal_res[1]} · "
                                        f"{'ilimitado' if unlimited else f'{self.target_fps} FPS'} · "
                                        f"geração x{self.frame_multiplier} · "
                                        f"motor {self.target_source.get('engine_type')} · "
                                        f"filtros {'ligados' if self.filters_enabled else 'desligados'}")

        try:
            while self.running:
                # 4. Check for the configured stop hotkey
                if win32api.GetAsyncKeyState(self.hotkeys["stop"]) & 0x8000:
                    print("Stop key pressed. Returning to menu...")
                    self.running = False
                    break

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False

                # Honest FPS: measured over a rolling half-second window, so a stalled
                # pipeline reports (and shows) the real rate instead of a stale value.
                loop_now = time.perf_counter()
                if loop_now - fps_window_start >= 0.5:
                    window = loop_now - fps_window_start
                    self.current_fps = fps_window_frames / window
                    self.generated_fps = generated_window / window
                    fps_window_frames = 0
                    generated_window = 0
                    fps_window_start = loop_now
                    diagnostics_time = self._log_periodic_status(loop_now, diagnostics_time)
                    self._auto_adapt(loop_now)

                # Precision pacing: sleep the bulk of the wait and spin only the
                # last two milliseconds. Windows rounds short sleeps up to its timer
                # resolution, and a 0.5 ms sleep that lasts 15 ms is visible as jitter.
                wait = frame_interval - (time.perf_counter() - last_display_time)
                if wait > 0.002:
                    time.sleep(wait - 0.002)
                    continue
                if wait > 0:
                    continue  # busy wait: shorter than the timer resolution

                # Buffer check: wait for at least 2 frames to be ready to absorb jitter
                # in Low Latency mode, we are more aggressive
                now = time.perf_counter()
                # Windows can drop the styles or steal focus back (Win key, Alt+Tab,
                # a game launcher): keep the overlay click-through and out of the way.
                if now - last_style_check >= WINDOW_STYLE_REFRESH_SECONDS:
                    last_style_check = now
                    self._apply_overlay_window_style(self.last_rect or rect, self.display_dim)
                min_buffer = 1 if self.low_latency else 3
                frame = self._pick_frame(now, min_buffer, stall_timeout, return_delay)

                if frame is not None:
                    if self._repeat_of_presented(frame):
                        # Nothing new arrived: presenting the same picture again would
                        # only burn CPU and inflate the frame counter.
                        time.sleep(UNLIMITED_IDLE_SLEEP)
                        continue
                    self.last_presented_frame = frame
                    last_display_time = now
                    
                    # Window sync: checking 15 times a second is enough to follow
                    # moves and resizes without paying for it on every frame.
                    self.sync_counter += 1
                    try:
                        sync_now = self.sync_counter >= max(1, self.target_fps // 8)
                        if sync_now:
                            self.sync_counter = 0
                            t_rect = get_source_rect(self.target_source)
                        else:
                            t_rect = self.last_rect
                        if self.last_rect != t_rect:
                            t_w, t_h = t_rect[2] - t_rect[0], t_rect[3] - t_rect[1]
                            

                            overlay_rect = get_source_monitor_rect(self.target_source) if self.scale_factor == -1 else t_rect
                            if self.scale_factor == -1:
                                d_w, d_h = overlay_rect[2] - overlay_rect[0], overlay_rect[3] - overlay_rect[1]
                            else:
                                d_w, d_h = int(t_w * self.scale_factor), int(t_h * self.scale_factor)
                            if d_w <= 0 or d_h <= 0:
                                continue
                            self.display_dim = (d_w, d_h)
                            if screen.get_width() != d_w or screen.get_height() != d_h:
                                if self.display_presenter is not None:
                                    screen = self.display_presenter.resize((d_w, d_h))
                                else:
                                    screen = pygame.display.set_mode((d_w, d_h), pygame.NOFRAME)
                            self._set_internal_resolution(t_rect)
                            self._apply_overlay_window_style(overlay_rect, (d_w, d_h))
                            self.last_rect = t_rect
                    except: pass

                    # A queued frame can still have the old size after a source resize.
                    if (frame.shape[1], frame.shape[0]) != self.display_dim:
                        frame = self._fit_display(frame)
                    if not frame.flags["C_CONTIGUOUS"]:
                        frame = np.ascontiguousarray(frame)
                    try:
                        # No copy: pygame reads the frame buffer directly.
                        surface = pygame.image.frombuffer(memoryview(frame), self.display_dim, 'RGB')
                    except (TypeError, ValueError):
                        surface = pygame.image.frombuffer(frame.tobytes(), self.display_dim, 'RGB')
                    screen.blit(surface, (0, 0))
                    
                    # Hotkeys & Stats
                    if win32api.GetAsyncKeyState(self.hotkeys["fps"]) & 0x8000:
                        if time.time() - self.hotkey_cooldown > 0.3:
                            self.show_fps = not self.show_fps
                            self.hotkey_cooldown = time.time()
                    
                    if win32api.GetAsyncKeyState(self.hotkeys["fsr"]) & 0x8000:
                        if time.time() - self.hotkey_cooldown > 0.3:
                            if self.filters_enabled:
                                self.fsr_mode = not self.fsr_mode
                                print(f"FSR Mode: {'ON' if self.fsr_mode else 'OFF'}")
                            else:
                                print("Image filters are off; enable them in the menu.")
                            self.hotkey_cooldown = time.time()
                    
                    if self.show_fps:
                        # Cosmetic only: a drawing problem must never stop the overlay.
                        try:
                            self._draw_hud(screen, font, small_font)
                        except Exception as exc:
                            print(f"Status panel disabled: {exc}")
                            self.show_fps = False

                    self._present_overlay(screen)
                    
                    self.frame_count += 1
                    fps_window_frames += 1
                    if self.last_frame_generated:
                        generated_window += 1
                        self._auto_probe_generated += 1
                else:
                    time.sleep(0.0005)

            # Removed clock.tick to rely on perf_counter pacing
        finally:
            self.running = False
            self.stop_event.set() # Stop the sub-process
            t_cap.join()
            t_post.join(timeout=2)
            p_proc.join(timeout=2)
            if p_proc.is_alive():
                p_proc.terminate()
                p_proc.join()
            for queue in (self.capture_queue, self.process_queue):
                queue.cancel_join_thread()
                queue.close()
            if self.display_presenter is not None:
                self.display_presenter.close()
                self.display_presenter = None
            pygame.quit()
        
        return True

def runtime_loader():
    """Heavy imports needed by the overlay and by the source list in the menu."""
    load_runtime()


def startup_memory_report():
    """RAM and pagefile numbers: a Windows commit failure is about exactly these two."""
    try:
        import psutil
        memory = psutil.virtual_memory()
        page = psutil.swap_memory()
        return (f"RAM {memory.available / 2**30:.1f} GB livres de {memory.total / 2**30:.1f} GB · "
                f"arquivo de paginação {page.used / 2**30:.1f} GB de {page.total / 2**30:.1f} GB")
    except Exception as exc:  # pragma: no cover - psutil ships with the app
        return f"informações de memória indisponíveis ({exc})"


def _show_failure_dialog(title, body):
    """Show a modal error through ctypes, which needs nothing the app may have failed to load.

    The frozen build runs windowed, so a traceback printed on the way out is never
    seen — which is how "it didn't open" becomes the only thing a user can report.
    """
    print(body)
    try:
        ctypes.windll.user32.MessageBoxW(None, body, title, 0x10)
    except Exception:
        pass  # no Windows dialog available: the log and the console already have it
    return body


def _log_failure(description, memory, traceback_text):
    try:
        diagnostics.write_now("início", description)
        diagnostics.write(f"memória no momento da falha: {memory}")
        if traceback_text:
            diagnostics.write(traceback_text.rstrip())
    except Exception:
        pass


def report_startup_failure(error, traceback_text=""):
    """Explain a failed start in the user's language, and write the details to the log."""
    if isinstance(error, RuntimeLoadError):
        module, original = error.module_name, error.error
    else:
        module, original = i18n.translate("app.title"), error
    memory = startup_memory_report()
    _log_failure(f"inicialização falhou ao carregar {module}: {original}", memory, traceback_text)
    body = i18n.translate("startup.failed_body", module=module, error=str(original), memory=memory,
                          log=str(diagnostics.log_path()), attempts=STARTUP_IMPORT_ATTEMPTS)
    return _show_failure_dialog(i18n.translate("startup.failed_title"), body)


def report_crash(error, traceback_text=""):
    """Something failed after the runtime loaded: say so instead of vanishing.

    An exception anywhere in the menu or in an overlay session used to end the process
    with nothing on screen. The log keeps the traceback; the dialog points at it.
    """
    memory = startup_memory_report()
    _log_failure(f"erro inesperado: {error}", memory, traceback_text)
    body = i18n.translate("crash.failed_body", error=str(error), memory=memory,
                          log=str(diagnostics.log_path()))
    return _show_failure_dialog(i18n.translate("crash.failed_title"), body)


def main():
    multiprocessing.freeze_support()
    # Use physical pixel coordinates on mixed-DPI monitor layouts.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    # Read the preferences file before anything heavy, so the splash can already
    # speak the saved language while OpenCV, numpy, pygame and DXCAM load.
    try:
        startup_settings = SettingsStore().load()
    except Exception as exc:
        print(f"Preferences unavailable ({exc}); using defaults")
        startup_settings = None
    i18n.set_language(startup_settings["language"] if startup_settings else None)
    try:
        run_splash(runtime_loader)
    except Exception as exc:
        # Never leave the user with a closed window and no explanation.
        report_startup_failure(exc, traceback.format_exc())
        return 1
    try:
        while True:
            app = FrameGenerationApp(target_fps=60)
            if not app.run():
                break
            print("Waiting for next selection...")
            time.sleep(0.5)
    except Exception as exc:
        report_crash(exc, traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    main()
