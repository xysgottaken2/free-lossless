import ctypes
import multiprocessing
import os
import threading
import time
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
win32gui = win32con = win32api = None


def runtime_loaded():
    return pygame is not None


def load_runtime():
    """Import the overlay dependencies. Calling it twice is harmless."""
    global cv2, np, pygame, ScreenCapture, RIFEEngine, RIFEONNXEngine, GameSelectorUI
    global get_source_rect, get_source_monitor_rect, AMDFilters, NvidiaAIUpscaler
    global win32gui, win32con, win32api
    if runtime_loaded():
        return
    import cv2 as cv2_module
    import numpy as numpy_module
    import pygame as pygame_module
    import win32api as win32api_module
    import win32con as win32con_module
    import win32gui as win32gui_module
    from capture import ScreenCapture as capture_class
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
    get_source_rect, get_source_monitor_rect = source_rect_function, monitor_rect_function
    GameSelectorUI = selector_ui

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


def capture_interval(target_fps, multiplier):
    """Seconds between captures: FPS / multiplier, so generated frames fill the rest."""
    try:
        multiplier = max(1, int(multiplier or 1))
    except (TypeError, ValueError):
        multiplier = 2
    rate = (target_fps / multiplier) if target_fps and target_fps > 0 else (30.0 / multiplier)
    return 1.0 / rate if rate > 0 else 1.0


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


def effective_capture_multiplier(fg_enabled, multiplier):
    """Interpolation fills the gaps, so captures slow down by the multiplier.

    With generation disabled nothing fills those gaps, so the capture has to keep
    the full target rate or the overlay would run at a fraction of it.
    """
    if not fg_enabled:
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
    import cv2

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
    internal_res = engine_config.get("internal_res", (800, 600))
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

            # Safety net: the capture worker already scales frames down.
            h, w = current_frame.shape[:2]
            if w > internal_res[0] or h > internal_res[1]:
                current_frame = cv2.resize(current_frame, internal_res, interpolation=cv2.INTER_LINEAR)

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
        self.display_dim = (1280, 720) # Actual output dimensions
        self.fsr_mode = False # Toggle for AMD CAS/EASU
        self.ai_mode = False # Toggle for NVIDIA AI SuperRes
        self.ai_upscaler = None

    def capture_worker(self):
        print("Capture worker started")
        last_frame = None
        multiplier = effective_capture_multiplier(getattr(self, "fg_enabled", True),
                                                   getattr(self, "frame_multiplier", 2))
        interval = capture_interval(self.target_fps, multiplier)

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

                now = time.perf_counter()
                if now - last_capture_time < interval:
                    time.sleep(0.001)
                    continue

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
        finally:
            # Release DXGI/GDI resources on the same worker that used them.
            self.capture.stop_capture()


    def _prepare_frame(self, frame):
        """Downscale a captured frame to the processing resolution."""
        max_w, max_h = self.internal_res
        height, width = frame.shape[:2]
        if width > max_w or height > max_h:
            frame = cv2.resize(frame, (max_w, max_h), interpolation=cv2.INTER_LINEAR)
        return frame

    def _publish_live_frame(self, frame):
        """Prepare a captured frame exactly like a generated one, for the fallback path.

        It goes through the same sharpening and upscale as a generated frame, so the
        image does not change look when the two sources swap.
        """
        try:
            display = self._render_for_display(frame)
        except Exception as exc:
            diagnostics.write_now("exibição", f"falha ao preparar frame ao vivo: {exc}")
            return
        put_latest(self.live_display_queue, display)

    def _newest_live_frame(self):
        """Newest prepared capture; repeats the previous one instead of showing nothing."""
        while True:
            try:
                self.last_live_display = self.live_display_queue.get_nowait()
            except Empty:
                return self.last_live_display

    def _pick_frame(self, now, min_buffer, stall_timeout, return_delay):
        """Show the newest frame available, from the generator or from the capture.

        Both paths are prepared exactly the same way, so a change of source is not
        visible in the image. What changes is the HUD chip, and that one only moves
        after a sustained stall or a sustained recovery: flipping it frame by frame
        is what made the panel look like it was flickering.
        """
        frame = None
        from_generator = False
        # Never display a backlog: if the generator produced more frames than the
        # overlay showed, the oldest ones are already out of date.
        while self.display_queue.qsize() > max(1, min_buffer):
            try:
                self.display_queue.get_nowait()
                self.dropped_generated += 1
            except Empty:
                break
        if self.display_queue.qsize() >= min_buffer or self.frame_count == 0:
            try:
                frame = self.display_queue.get_nowait()
                from_generator = frame is not None
            except Empty:
                frame = None
        if frame is None:
            # Nothing generated is ready: the newest capture keeps the image moving.
            frame = self._newest_live_frame()

        if from_generator:
            self.starving_since = None
            if self.live_fallback:
                if self.healthy_since is None:
                    self.healthy_since = now
                elif now - self.healthy_since >= return_delay:
                    self.live_fallback = False
                    self.healthy_since = None
                    print("Frame generation is keeping up again.")
                    diagnostics.write_now("exibição", "geração voltou a acompanhar o ritmo (FG)")
        else:
            self.healthy_since = None
            if self.starving_since is None:
                self.starving_since = now
            if not self.live_fallback and now - self.starving_since >= stall_timeout:
                self.live_fallback = True
                print("Frame generation cannot keep up: showing the live capture.")
                diagnostics.write_now("exibição", "geração não acompanha o ritmo; "
                                                  "exibindo a captura direta (LIVE)")

        self.want_live_frames = self.live_fallback
        self.last_frame_generated = from_generator
        return frame

    def _prepare_ai_upscaler(self):
        """Measure the AI upscaler once and drop it when it cannot keep up.

        The same FSRCNN model costs a few milliseconds on a GPU and hundreds of
        milliseconds on the CPU. Rather than stalling every frame, the filter is
        turned off for the session with the reason written to the log (and to the
        console), and the normal sharpening/upscale path takes over.
        """
        if not (self.ai_mode and self.ai_upscaler):
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

    def _render_for_display(self, frame):
        """Sharpen at the processing resolution, then upscale once for the display.

        Sharpening before the upscale is the difference between a few milliseconds
        and tens of milliseconds per frame on a 1080p or larger display.
        """
        needs_upscale = (frame.shape[1], frame.shape[0]) != self.display_dim
        if self.ai_mode and self.ai_upscaler:
            frame = self.ai_upscaler.upscale(frame)
            if (frame.shape[1], frame.shape[0]) != self.display_dim:
                frame = cv2.resize(frame, self.display_dim, interpolation=cv2.INTER_LINEAR)
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
        """Prepare every generated frame for the display."""
        print("Post-processing worker started")
        while self.running:
            try:
                frame = self.process_queue.get(timeout=0.02)
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
        
        # Scaling config
        scale_val = self.target_source["scale"]
        if scale_val == "Fullscreen":
            self.scale_factor = -1 # Special flag for fullscreen
        else:
            self.scale_factor = float(scale_val)
            
        algo_val = self.target_source["algo"]
        if algo_val == "Bilinear": self.upscale_algo = cv2.INTER_LINEAR
        elif algo_val == "Bicubic": self.upscale_algo = cv2.INTER_CUBIC
        elif algo_val == "Lanczos": self.upscale_algo = cv2.INTER_LANCZOS4
        elif "FSR" in algo_val:
            self.fsr_mode = True
        elif "AI" in algo_val:
            self.ai_mode = True
            self.ai_upscaler = NvidiaAIUpscaler()
            
        self.fg_enabled = self.target_source.get("fg_enabled", True)
        
        self.sharpness = self.target_source["sharpness"] / 100.0 * 2.0 # Scale 0-100 to 0.0-2.0
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

        # Performance tuning: Set internal resolution limit
        # Performance Mode (Alta Res) uses 1280x720, Standard uses 800x600
        max_w, max_h = (1280, 720) if self.target_source.get("performance_mode") else (800, 600)
        
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > max_w: self.internal_res = (max_w, max_h)
        else: self.internal_res = (w, h)
        
        # Initial display dimensions
        if self.scale_factor == -1:
            self.display_dim = (monitor_rect[2] - monitor_rect[0], monitor_rect[3] - monitor_rect[1])
        else:
            self.display_dim = (int(w * self.scale_factor), int(h * self.scale_factor))

        print(f"Targeting: {self.target_source['title']} | Mode: {self.target_source['mode']} | FPS: {self.target_fps} | Scale: {scale_val} | Frame gen: x{multiplier}")
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
        display_flags = pygame.NOFRAME

        if d_w <= 0 or d_h <= 0:
            print("Invalid window dimensions.")
            return True

        # Setup Borderless Window
        screen = pygame.display.set_mode((d_w, d_h), display_flags)
        pygame.display.set_caption(i18n.translate("app.title"))
        
        # FPS Font
        pygame.font.init()
        font = pygame.font.SysFont("Arial", 24, bold=True)
        small_font = pygame.font.SysFont("Arial", 18, bold=True)
        
        hwnd_pygame = pygame.display.get_wm_info()["window"]
        
        # 1. Exclude this window from screen capture (Win 10+)
        try:
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd_pygame, WDA_EXCLUDEFROMCAPTURE)
        except Exception as e:
            print(f"Capture exclusion not available: {e}")

        # 2. Make Click-Through
        ex_style = win32gui.GetWindowLong(hwnd_pygame, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(hwnd_pygame, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

        # 3. Set to Always On Top on the selected source's monitor.
        win32gui.SetWindowPos(
            hwnd_pygame, win32con.HWND_TOPMOST, overlay_rect[0], overlay_rect[1],
            d_w, d_h, win32con.SWP_SHOWWINDOW,
        )
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
        
        self._prepare_ai_upscaler()

        t_cap.start()
        p_proc.start()
        t_post.start()
        
        frame_interval = 1.0 / self.target_fps
        # The generator needs to miss a whole frame before LIVE frames take over, and
        # it has to prove it recovered before generated frames come back. Without the
        # second delay the two sources alternate every frame, which the eye reads as
        # flicker.
        stall_timeout = max(frame_interval * 2, 0.03)
        return_delay = max(stall_timeout * 3, 0.3)
        last_display_time = time.perf_counter()
        fps_window_start = last_display_time
        fps_window_frames = 0
        generated_window = 0
        diagnostics_time = last_display_time
        self.sync_counter = 0
        diagnostics.reset()
        diagnostics.write_now("início", f"overlay {self.display_dim[0]}x{self.display_dim[1]} · "
                                        f"interno {self.internal_res[0]}x{self.internal_res[1]} · "
                                        f"{self.target_fps} FPS · geração x{self.frame_multiplier} · "
                                        f"motor {self.target_source.get('engine_type')}")

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
                    if loop_now - diagnostics_time >= 5.0:
                        diagnostics_time = loop_now
                        source = "live" if self.live_fallback else "generated"
                        queue_size = self.display_queue.qsize()
                        print(f"[overlay] {self.current_fps:5.1f} FPS exibidos  ·  "
                              f"{self.generated_fps:5.1f} frames gerados/s  ·  fila {queue_size}  ·  "
                              f"{source}  ·  captura {self.frame_multiplier}x")
                        diagnostics.write_now("exibição", f"{self.current_fps:5.1f} FPS exibidos · "
                                                           f"{self.generated_fps:5.1f} gerados/s · "
                                                           f"filas captura {self.capture_queue.qsize()}"
                                                           f"/{self.capture_queue.maxsize} · pós "
                                                           f"{self.process_queue.qsize()}"
                                                           f"/{self.process_queue.maxsize} · exibição "
                                                           f"{queue_size}/{self.display_queue.maxsize} · "
                                                           f"{source} · {self.dropped_generated} descartados")

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
                min_buffer = 1 if self.low_latency else 3
                frame = self._pick_frame(now, min_buffer, stall_timeout, return_delay)

                if frame is not None:
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
                            
                            # Update internal res cap immediately
                            max_w, max_h = (1280, 720) if self.target_source.get("performance_mode") else (800, 600)
                            if t_w > max_w: self.internal_res = (max_w, max_h)
                            else: self.internal_res = (t_w, t_h)

                            overlay_rect = get_source_monitor_rect(self.target_source) if self.scale_factor == -1 else t_rect
                            if self.scale_factor == -1:
                                d_w, d_h = overlay_rect[2] - overlay_rect[0], overlay_rect[3] - overlay_rect[1]
                            else:
                                d_w, d_h = int(t_w * self.scale_factor), int(t_h * self.scale_factor)
                            if d_w <= 0 or d_h <= 0:
                                continue
                            self.display_dim = (d_w, d_h)
                            hwnd_p = pygame.display.get_wm_info()["window"]
                            if screen.get_width() != d_w or screen.get_height() != d_h:
                                screen = pygame.display.set_mode((d_w, d_h), pygame.NOFRAME)
                                hwnd_p = pygame.display.get_wm_info()["window"]
                                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd_p, 0x00000011)
                                ex = win32gui.GetWindowLong(hwnd_p, win32con.GWL_EXSTYLE)
                                win32gui.SetWindowLong(hwnd_p, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
                            win32gui.SetWindowPos(hwnd_p, win32con.HWND_TOPMOST, overlay_rect[0], overlay_rect[1], d_w, d_h, win32con.SWP_NOACTIVATE)
                            self.last_rect = t_rect
                    except: pass

                    # A queued frame can still have the old size after a source resize.
                    if (frame.shape[1], frame.shape[0]) != self.display_dim:
                        frame = cv2.resize(frame, self.display_dim, interpolation=cv2.INTER_LINEAR)
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
                            self.fsr_mode = not self.fsr_mode
                            self.hotkey_cooldown = time.time()
                            print(f"FSR Mode: {'ON' if self.fsr_mode else 'OFF'}")
                    
                    if self.show_fps:
                        # Cosmetic only: a drawing problem must never stop the overlay.
                        try:
                            self._draw_hud(screen, font, small_font)
                        except Exception as exc:
                            print(f"Status panel disabled: {exc}")
                            self.show_fps = False

                    pygame.display.flip()
                    
                    self.frame_count += 1
                    fps_window_frames += 1
                    if self.last_frame_generated:
                        generated_window += 1
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
            pygame.quit()
        
        return True

def runtime_loader():
    """Heavy imports needed by the overlay and by the source list in the menu."""
    load_runtime()


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
    run_splash(runtime_loader)
    while True:
        app = FrameGenerationApp(target_fps=60)
        if not app.run():
            break
        print("Waiting for next selection...")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
