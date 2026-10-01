import cv2
import numpy as np
import pygame
import threading
import time
import ctypes
import multiprocessing
from queue import Queue, Full
from capture import ScreenCapture
from engine import RIFEEngine, RIFEONNXEngine
from ui import GameSelectorUI
from selector import get_source_rect, get_source_monitor_rect
from tkinter import messagebox
from filters import AMDFilters, NvidiaAIUpscaler
import win32gui
import win32con
import win32api
import os

def processing_subroutine(capture_queue, process_queue, engine_config, stop_event):
    """
    Standalone subroutine for multiprocessing.
    """
    from engine import RIFEEngine, RIFEONNXEngine
    import cv2
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

    print(f"Sub-process processing worker started (PID: {os.getpid()})")
    
    while not stop_event.is_set():
        try:
            # We use a small timeout to check the stop_event periodically
            current_frame = capture_queue.get(timeout=0.1)
            
            # Internal Scaling
            h, w = current_frame.shape[:2]
            if w > internal_res[0] or h > internal_res[1]:
                current_frame = cv2.resize(current_frame, internal_res, interpolation=cv2.INTER_LINEAR)

            if fg_enabled and last_frame is not None:
                inter_frame = engine.interpolate(last_frame, current_frame)
                process_queue.put(inter_frame)
                process_queue.put(current_frame)
            else:
                process_queue.put(current_frame)
            
            last_frame = current_frame
        except:
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

    def capture_worker(self):
        print("Capture worker started")
        last_frame = None
        # Target capture is exactly half the display FPS
        capture_interval = 1.0 / (self.target_fps / 2) if self.target_fps > 0 else 1.0/30.0

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
                if now - last_capture_time < capture_interval:
                    time.sleep(0.001)
                    continue

                last_capture_time = now
                rect = self.capture.region
                if rect[2] <= rect[0] or rect[3] <= rect[1]:
                    continue
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
                        try:
                            self.capture_queue.put_nowait(frame)
                            last_frame = frame
                        except Full:
                            pass
        finally:
            # Release DXGI/GDI resources on the same worker that used them.
            self.capture.stop_capture()


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
                raise ValueError("A fonte selecionada não tem uma área válida.")
        except Exception as exc:
            messagebox.showerror("Fonte indisponível", str(exc))
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
        
        # Adaptive Buffer based on latency selection
        self.low_latency = self.target_source.get("low_latency", True)
        display_buf_size = 3 if self.low_latency else 15
        self.display_queue = Queue(maxsize=display_buf_size)

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

        print(f"Targeting: {self.target_source['title']} | Mode: {self.target_source['mode']} | FPS: {self.target_fps} | Scale: {scale_val}")
        print("Press F11 to stop, F10 to toggle FPS.")
        return True

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
        pygame.display.set_caption("FG Overlay")
        
        # FPS Font
        pygame.font.init()
        font = pygame.font.SysFont("Arial", 24, bold=True)
        
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

        clock = pygame.time.Clock()
        self.running = True
        self.start_time = time.time()
        
        # Prepare config for sub-process
        engine_config = {
            "engine_type": self.target_source.get("engine_type"),
            "ultra_smooth": self.ultra_smooth,
            "fg_enabled": self.fg_enabled,
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
        
        t_cap.start()
        p_proc.start()
        t_post.start()
        
        frame_interval = 1.0 / self.target_fps
        last_display_time = time.perf_counter()

        try:
            while self.running:
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
                    
                    # Window sync (minimal overhead)
                    try:
                        t_rect = get_source_rect(self.target_source)
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
                        frame = cv2.resize(frame, self.display_dim, interpolation=self.upscale_algo)
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

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Use physical pixel coordinates on mixed-DPI monitor layouts.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    while True:
        app = FrameGenerationApp(target_fps=60)
        if not app.run():
            break
        print("Waiting for next selection...")
        time.sleep(0.5)
