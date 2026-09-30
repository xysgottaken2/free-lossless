import cv2
import numpy as np
import pygame
import threading
import time
import ctypes
import multiprocessing
from queue import Queue
from capture import ScreenCapture
from engine import RIFEEngine, RIFEONNXEngine
from selector import WindowSelector
from filters import AMDFilters, NvidiaAIUpscaler
import win32gui
import win32con
import win32api
import os

from targets import list_monitors, normalize_source, resolve_capture_target

def processing_subroutine(capture_queue, process_queue, engine_config, stop_event):
    """
    Standalone subroutine for multiprocessing.

    Stage chain: Resize -> [DLSS 5 Neural Rendering (optional)] -> [RIFE (optional)].
    A DLSS 5 failure never kills this worker: the stage disables itself and the
    frames keep flowing to the overlay (RIFE-only pipeline).
    """
    from engine import RIFEEngine, RIFEONNXEngine
    from neural import create_renderer, log_rife
    from pipeline import FramePipeline
    import numpy as np

    # Initialize engine inside the process
    if engine_config.get("engine_type") == "AI (RIFE ONNX)":
        engine = RIFEONNXEngine()
    else:
        engine = RIFEEngine()
        
    if hasattr(engine, 'set_high_precision'):
        engine.set_high_precision(engine_config.get("ultra_smooth", False))

    fg_enabled = engine_config.get("fg_enabled", True)
    internal_res = engine_config.get("internal_res", (800, 600))
    last_frame = None

    # Optional DLSS 5 Neural Rendering stage (external NVIDIA runtime in native/).
    dlss5_options = engine_config.get("dlss5") or {}
    renderer = create_renderer(
        dlss5_options,
        expected_size=(internal_res[0], internal_res[1]),
    )

    pipeline = FramePipeline(
        engine=engine,
        renderer=renderer,
        internal_res=internal_res,
        fg_enabled=fg_enabled,
    )

    print(f"Sub-process processing worker started (PID: {os.getpid()})")
    
    while not stop_event.is_set():
        try:
            # We use a small timeout to check the stop_event periodically
            current_frame = capture_queue.get(timeout=0.1)

            frames = pipeline.process_frame(current_frame)
            for f in frames:
                process_queue.put(f)
        except:
            continue

    try:
        renderer.shutdown()
    except Exception:
        pass

class FrameGenerationApp:
    def __init__(self, target_fps=60):
        self.target_fps = target_fps
        self.capture = ScreenCapture()
        self.engine = RIFEEngine()
        self.running = False
        self.target_window = None
        self.capture_target = None
        self.selection = None
        self._ui = None
        self.stop_event = None
        # Persistent configuration (config/freelossless.json)
        try:
            from config import AppConfig
            self.app_config = AppConfig.load()
        except Exception as e:
            print(f"[CONFIG] Using in-memory defaults: {e}")
            from config import AppConfig
            self.app_config = AppConfig()
        
        # Queues for pipeline (Use multiprocessing queues for inter-process communication)
        self.capture_queue = multiprocessing.Queue(maxsize=2)
        self.process_queue = multiprocessing.Queue(maxsize=3)
        self.display_queue = Queue(maxsize=5) # Lighter buffer for lower latency
        
        # Stats
        self.frame_count = 0
        self.start_time = 0
        self.current_fps = 0
        
        # Window & Performance management
        self.last_rect = None
        self.show_fps = True
        self.hotkey_cooldown = 0
        self.scale_factor = 1.0
        self.upscale_algo = cv2.INTER_LINEAR
        self.sharpness = 0.3
        self.internal_res = (800, 600) # Default target resolution for processing
        self.display_dim = (1280, 720) # Actual output dimensions
        self.fsr_mode = False # Toggle for AMD CAS/EASU
        self.ai_mode = False # Toggle for NVIDIA AI SuperRes
        self.ai_upscaler = None
        self.fg_enabled = True
        self.ultra_smooth = False
        self.performance_mode = False
        self.low_latency = True
        self.engine_type = "AI (RIFE ONNX)"

    # ---------------------------------------------------------- UI plumbing
    def attach_ui(self, ui):
        """Reference to the Tk window so the display loop can pump events."""
        self._ui = ui

    def _pump_ui(self):
        """Keep the Start/Stop button responsive while the overlay runs."""
        if self._ui is not None:
            try:
                self._ui.process_events()
            except Exception:
                self.running = False

    def capture_worker(self):
        print("Capture worker started")
        last_frame = None
        # Target capture is exactly half the display FPS
        capture_interval = 1.0 / (self.target_fps / 2) if self.target_fps > 0 else 1.0/30.0
        
        last_capture_time = time.perf_counter()
        
        while self.running:
            # Update region based on window position (Window mode only)
            if self.target_window:
                try:
                    rect = WindowSelector.get_window_rect(self.target_window["hwnd"])
                    self.capture.region = rect # Update region
                except:
                    print("Lost window, stopping...")
                    self.running = False
                    break
            
            now = time.perf_counter()
            if now - last_capture_time < capture_interval:
                time.sleep(0.001)
                continue
            
            last_capture_time = now
            frame = self.capture.capture_frame()
            
            if frame is not None:
                # Optimized duplicate check
                is_duplicate = False
                if last_frame is not None:
                    try:
                        # Slice check is very fast
                        if np.array_equal(frame[10:30:2, 10:30:2], last_frame[10:30:2, 10:30:2]):
                            if np.array_equal(frame[::60, ::60], last_frame[::60, ::60]):
                                is_duplicate = True
                    except: pass
                
                if not is_duplicate:
                    if self.capture_queue.full():
                        try: self.capture_queue.get_nowait()
                        except: pass
                    self.capture_queue.put(frame)
                    last_frame = frame


    def post_processing_worker(self):
        print("Post-processing worker started")
        while self.running:
            if not self.process_queue.empty():
                frame = self.process_queue.get()
                
                # Push to display
                if self.ai_mode and self.ai_upscaler:
                    # AI Reconstruction
                    frame = self.ai_upscaler.upscale(frame)
                    # Final fit to display if AI output differs
                    if frame.shape[1] != self.display_dim[0] or frame.shape[0] != self.display_dim[1]:
                        frame = cv2.resize(frame, self.display_dim, interpolation=cv2.INTER_LINEAR)
                elif self.fsr_mode:
                    # High-Speed Resizing (EASU-style if FSR mode enabled)
                    if frame.shape[1] != self.display_dim[0] or frame.shape[0] != self.display_dim[1]:
                        frame = AMDFilters.apply_easu(frame, self.display_dim)
                    else:
                        frame = AMDFilters.apply_cas(frame, self.sharpness)
                else:
                    if frame.shape[1] != self.display_dim[0] or frame.shape[0] != self.display_dim[1]:
                        frame = cv2.resize(frame, self.display_dim, interpolation=self.upscale_algo)
                    
                    # Apply simple sharpening (Fallback)
                    if self.sharpness > 0:
                        blurred = cv2.GaussianBlur(frame, (0, 0), 3)
                        frame = cv2.addWeighted(frame, 1.0 + self.sharpness, blurred, -self.sharpness, 0)

                if self.display_queue.full():
                    try: self.display_queue.get_nowait()
                    except: pass
                self.display_queue.put(frame)
            else:
                # Slight sleep to reduce CPU usage when idle
                time.sleep(0.0005)

    # ----------------------------------------------------- selection / start
    def apply_selection(self, selection):
        """Configure capture + processing from a UI selection dict (no UI calls)."""
        self.selection = selection

        # ---- capture target: Window (one app) or Full Screen (monitor) ----
        source = normalize_source(selection.get("source", "window"))
        self.capture_target = resolve_capture_target(
            selection,
            monitors=list_monitors(),
            window_rect_getter=WindowSelector.get_window_rect,
        )
        if self.capture_target.source == "window":
            self.target_window = {
                "hwnd": selection["hwnd"],
                "title": selection.get("title", ""),
            }
        else:
            self.target_window = None

        # Re-initialize capture with correct mode and region
        self.capture = ScreenCapture.for_target(self.capture_target, mode=selection.get("mode", "bitblt"))
        self.target_fps = selection.get("fps", 60)
        
        # Scaling config
        scale_val = selection.get("scale", "1.0")
        if scale_val == "Fullscreen":
            self.scale_factor = -1 # Special flag for fullscreen
        else:
            self.scale_factor = float(scale_val)
            
        algo_val = selection.get("algo", "Lanczos")
        self.fsr_mode = False
        self.ai_mode = False
        self.ai_upscaler = None
        self.upscale_algo = cv2.INTER_LINEAR
        if algo_val == "Bilinear": self.upscale_algo = cv2.INTER_LINEAR
        elif algo_val == "Bicubic": self.upscale_algo = cv2.INTER_CUBIC
        elif algo_val == "Lanczos": self.upscale_algo = cv2.INTER_LANCZOS4
        elif "FSR" in algo_val: self.fsr_mode = True
        elif "AI" in algo_val:
            self.ai_mode = True
            self.ai_upscaler = NvidiaAIUpscaler()
            
        self.fg_enabled = selection.get("fg_enabled", True)
        
        self.sharpness = selection.get("sharpness", 20) / 100.0 * 2.0 # Scale 0-100 to 0.0-2.0
        self.ultra_smooth = selection.get("ultra_smooth", False)
        self.performance_mode = selection.get("performance_mode", False)
        self.engine_type = selection.get("engine_type", "AI (RIFE ONNX)")
        if self.engine_type == "AI (RIFE ONNX)":
            self.engine = RIFEONNXEngine()
        else:
            self.engine = RIFEEngine()
            
        self.engine.set_high_precision(self.ultra_smooth) if hasattr(self.engine, 'set_high_precision') else None

        # --- DLSS 5 Neural Rendering options (persisted) ---
        dlss5_opts = self.app_config.dlss5
        dlss5_opts["enabled"] = bool(selection.get("dlss5_enabled", dlss5_opts.get("enabled", False)))
        dlss5_opts["passes"] = int(selection.get("dlss5_passes", dlss5_opts.get("passes", 1)))
        dlss5_opts["style"] = int(selection.get("dlss5_style", dlss5_opts.get("style", 1)))
        dlss5_opts["intensity"] = float(selection.get("dlss5_intensity", dlss5_opts.get("intensity", 0.35)))
        dlss5_opts["work_scale"] = float(selection.get("dlss5_work_scale", dlss5_opts.get("work_scale", 1.0)))
        dlss5_opts["auto_mask"] = 1 if selection.get("dlss5_auto_mask", bool(dlss5_opts.get("auto_mask", 1))) else 0
        self.app_config.rife["enabled"] = bool(self.fg_enabled)
        self.app_config.rife["engine_type"] = self.engine_type
        self.app_config.rife["ultra_smooth"] = bool(self.ultra_smooth)

        # --- Capture source persistence (window / fullscreen + monitor) ---
        self.app_config.capture["source"] = self.capture_target.source
        self.app_config.capture["monitor"] = int(self.capture_target.output_idx)
        try:
            self.app_config.save()
        except Exception as e:
            print(f"[CONFIG] Could not save configuration: {e}")
        
        # Adaptive Buffer based on latency selection
        self.low_latency = selection.get("low_latency", True)
        display_buf_size = 3 if self.low_latency else 15
        self.display_queue = Queue(maxsize=display_buf_size)

        # Initial region (window rect or monitor rect)
        rect = self.capture_target.rect
        self.capture.region = rect if not self.capture_target.full_output else self.capture.region
        self.last_rect = rect
        
        # Performance tuning: Set internal resolution limit
        # Performance Mode (High Res) uses 1280x720, Standard uses 800x600
        max_w, max_h = (1280, 720) if self.performance_mode else (800, 600)
        
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > max_w: self.internal_res = (max_w, max_h)
        else: self.internal_res = (w, h)
        
        # Initial display dimensions
        if self.scale_factor == -1:
            info = win32api.GetSystemMetrics(win32con.SM_CXSCREEN), win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.display_dim = info
        else:
            self.display_dim = (int(w * self.scale_factor), int(h * self.scale_factor))

        title = self.target_window['title'] if self.target_window else self.capture_target.label
        print(f"Targeting: {title} | Source: {self.capture_target.source} | Mode: {selection.get('mode')} | FPS: {self.target_fps} | Scale: {scale_val}")
        print("Press Stop (or F11) to stop, F10 to toggle FPS, F9 to toggle FSR.")

    def start_pipeline(self, selection):
        """Run the whole pipeline (capture -> DLSS 5/RIFE -> overlay).

        Blocking until :meth:`request_stop` (Stop button, F11 or window close).
        Returns True when the pipeline has been torn down cleanly.
        """
        self.apply_selection(selection)

        pygame.init()
        # Initial capture size
        rect = self.capture_target.rect
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        
        # Calculate display size
        if self.scale_factor == -1: # Fullscreen
            info = pygame.display.Info()
            d_w, d_h = info.current_w, info.current_h
            display_flags = pygame.NOFRAME | pygame.FULLSCREEN
        else:
            d_w, d_h = int(w * self.scale_factor), int(h * self.scale_factor)
            display_flags = pygame.NOFRAME

        if d_w <= 0 or d_h <= 0:
            print("Invalid window dimensions.")
            return True

        # Setup Borderless Window
        screen = pygame.display.set_mode((d_w, d_h), display_flags)
        pygame.display.set_caption("FG Overlay")
        
        # FPS Font
        pygame.font.init()
        font = pygame.font.SysFont("Arial", 24, bold=True)
        
        hwnd_pygame = pygame.display.get_wm_info()["window"]
        hwnd_p = hwnd_pygame
        
        # 1. Exclude this window from screen capture (Win 10+)
        try:
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd_pygame, WDA_EXCLUDEFROMCAPTURE)
        except Exception as e:
            print(f"Capture exclusion not available: {e}")

        # 2. Make Click-Through
        ex_style = win32gui.GetWindowLong(hwnd_pygame, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(hwnd_pygame, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

        # 3. Set to Always On Top
        if self.scale_factor == -1: # Fullscreen
            win32gui.SetWindowPos(hwnd_pygame, win32con.HWND_TOPMOST, 0, 0, d_w, d_h, win32con.SWP_SHOWWINDOW)
        else:
            win32gui.SetWindowPos(hwnd_pygame, win32con.HWND_TOPMOST, rect[0], rect[1], d_w, d_h, win32con.SWP_SHOWWINDOW)
        self.last_rect = rect

        # Increase process priority for better smoothness
        try:
            import psutil
            p = psutil.Process()
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        except: pass

        clock = pygame.time.Clock()
        self.running = True
        self.frame_count = 0
        self.start_time = time.time()
        
        # Prepare config for sub-process
        engine_config = {
            "engine_type": self.engine_type,
            "ultra_smooth": self.ultra_smooth,
            "fg_enabled": self.fg_enabled,
            "internal_res": self.internal_res,
            "dlss5": self.app_config.dlss5_options(),
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
        
        t_cap.start()
        p_proc.start()
        t_post.start()
        
        frame_interval = 1.0 / self.target_fps
        last_display_time = time.perf_counter()

        try:
            while self.running:
                # Keep the Tk UI alive so the Stop button always works
                self._pump_ui()
                if not self.running:
                    break

                # 4. Check for Global Hotkey (F11)
                # VK_F11 = 0x7A
                if win32api.GetAsyncKeyState(0x7A) & 0x8000:
                    print("Stop key pressed. Returning to menu...")
                    self.running = False
                    break

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                
                # Precision Pacing Logic
                now = time.perf_counter()
                if now - last_display_time < frame_interval:
                    # Busy-wait for the last 1ms for sub-ms precision
                    if frame_interval - (now - last_display_time) < 0.001:
                        pass # Busy wait
                    else:
                        time.sleep(0.0005)
                    continue

                # Buffer check: wait for at least 2 frames to be ready to absorb jitter
                # in Low Latency mode, we are more aggressive
                min_buffer = 1 if self.low_latency else 3
                if self.display_queue.qsize() < min_buffer and self.frame_count > 0:
                    time.sleep(0.0005) # Shorter wait
                    continue

                if not self.display_queue.empty():
                    frame = self.display_queue.get()
                    last_display_time = now
                    
                    # Window sync (minimal overhead). Full Screen mode uses a
                    # static monitor rectangle, so this only runs for windows.
                    if self.target_window:
                        try:
                            t_rect = WindowSelector.get_window_rect(self.target_window["hwnd"])
                            if self.last_rect != t_rect:
                                t_w, t_h = t_rect[2] - t_rect[0], t_rect[3] - t_rect[1]
                                
                                # Update internal res cap immediately
                                max_w, max_h = (1280, 720) if self.performance_mode else (800, 600)
                                if t_w > max_w: self.internal_res = (max_w, max_h)
                                else: self.internal_res = (t_w, t_h)

                                if self.scale_factor != -1:
                                    d_w, d_h = int(t_w * self.scale_factor), int(t_h * self.scale_factor)
                                    self.display_dim = (d_w, d_h)
                                    if screen.get_width() != d_w or screen.get_height() != d_h:
                                        screen = pygame.display.set_mode((d_w, d_h), pygame.NOFRAME)
                                        hwnd_p = pygame.display.get_wm_info()["window"]
                                        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd_p, 0x00000011)
                                        ex = win32gui.GetWindowLong(hwnd_p, win32con.GWL_EXSTYLE)
                                        win32gui.SetWindowLong(hwnd_p, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
                                    win32gui.SetWindowPos(hwnd_p, win32con.HWND_TOPMOST, t_rect[0], t_rect[1], d_w, d_h, win32con.SWP_NOACTIVATE)
                                self.last_rect = t_rect
                        except: pass

                    # Blit and Flip (Now ultra-fast as frame is pre-processed)
                    surface = pygame.image.frombuffer(frame.tobytes(), self.display_dim, 'RGB')
                    screen.blit(surface, (0, 0))
                    
                    # Hotkeys & Stats
                    if win32api.GetAsyncKeyState(0x79) & 0x8000: # F10
                        if time.time() - self.hotkey_cooldown > 0.3:
                            self.show_fps = not self.show_fps
                            self.hotkey_cooldown = time.time()
                    
                    if win32api.GetAsyncKeyState(0x78) & 0x8000: # F9
                        if time.time() - self.hotkey_cooldown > 0.3:
                            self.fsr_mode = not self.fsr_mode
                            self.hotkey_cooldown = time.time()
                            print(f"FSR Mode: {'ON' if self.fsr_mode else 'OFF'}")
                    
                    if self.show_fps:
                        status_color = (0, 255, 0)
                        fps_text = font.render(f"FPS: {self.current_fps:.1f}", True, status_color)
                        fsr_text = font.render(f"(F9) FSR: {'ON' if self.fsr_mode else 'OFF'}", True, (255, 200, 0) if self.fsr_mode else (150, 150, 150))
                        
                        ai_text = font.render(f"AI SuperRes: {'ON' if self.ai_mode else 'OFF'}", True, (0, 255, 200) if self.ai_mode else (150, 150, 150))

                        # Extra status for new modes
                        mode_text_str = "STD"
                        if self.ultra_smooth: mode_text_str = "SMOOTH"
                        mode_text = font.render(f"Mode: {mode_text_str}", True, (0, 200, 255))

                        # Draw status box
                        bg_rect = pygame.Rect(10, 10, 200, 110)
                        pygame.draw.rect(screen, (0, 0, 0), bg_rect)
                        pygame.draw.rect(screen, (50, 50, 50), bg_rect, 2)
                        
                        screen.blit(fps_text, (20, 15))
                        screen.blit(fsr_text, (20, 40))
                        screen.blit(ai_text, (20, 65))
                        screen.blit(mode_text, (20, 90))

                    pygame.display.flip()
                    
                    self.frame_count += 1
                    if self.frame_count % 30 == 0:
                        t_now = time.time()
                        self.current_fps = 30 / (t_now - self.start_time)
                        self.start_time = t_now
                else:
                    time.sleep(0.0005)

            # Removed clock.tick to rely on perf_counter pacing
        finally:
            self.stop_pipeline()
        
        return True

    def request_stop(self):
        """Ask the running pipeline to exit (Stop button or window close)."""
        self.running = False

    def stop_pipeline(self):
        """Tear down workers/capture/overlay (idempotent)."""
        self.running = False
        try:
            if self.stop_event is not None:
                self.stop_event.set() # Stop the sub-process
        except Exception:
            pass
        try:
            self.capture.stop_capture()
        except Exception:
            pass
        try:
            pygame.quit()
        except Exception:
            pass

if __name__ == "__main__":
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)

    from app_controller import AppController
    from ui import GameSelectorUI

    app = FrameGenerationApp(target_fps=60)
    ui = GameSelectorUI(app_config=app.app_config)
    controller = AppController(host=app, ui=ui)
    ui.bind_controller(controller)
    app.attach_ui(ui)
    ui.mainloop()
    print("Free Lossless closed.")
