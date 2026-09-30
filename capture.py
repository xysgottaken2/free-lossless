import time
import cv2
import numpy as np
import win32gui
import win32ui
import win32con
import win32api

class ScreenCapture:
    def __init__(self, region=None, device_idx=0, output_color="RGB", mode="dxcam",
                 output_idx=None, desktop_coordinates=False):
        """
        Initialize the capture.
        :param region: Tuple of (left, top, right, bottom). If None, captures full screen.
        :param mode: "dxcam" or "bitblt"
        :param desktop_coordinates: Resolve a desktop region to its DXGI output.
        """
        self.mode = mode
        self.camera = None
        self.device_idx = device_idx
        self.output_idx = output_idx
        self.output_color = output_color
        self.desktop_coordinates = desktop_coordinates
        self._camera_key = None
        
        self.region = region
        self.is_capturing = False

        # BitBlt persistent resources
        self._hwnd_dc = None
        self._mfc_dc = None
        self._save_dc = None
        self._save_bitmap = None
        self._last_dims = (0, 0)

        if self.mode == "dxcam":
            # Initialize comtypes/DXCAM on the caller's main thread, not the
            # short-lived capture worker. BitBlt still has no DXGI dependency.
            try:
                import dxcam
            except Exception as exc:
                print(f"DXCAM unavailable: {exc}. Falling back to BitBlt.")
                self.mode = "bitblt"
        
    def capture_frame(self):
        """
        Captures a single frame based on the current mode.
        """
        if self.mode == "dxcam":
            return self._capture_dxcam()
        else:
            return self._capture_bitblt()

    @staticmethod
    def _resolve_dxcam_output(dxcam, device, monitor_rect):
        # dxcam 0.0.5 exposes no public DeviceName -> output index mapping.
        # Keep this version-specific adapter isolated; never guess by list order.
        factory = getattr(dxcam, "__factory", None)
        for device_idx, outputs in enumerate(getattr(factory, "outputs", [])):
            for output_idx, output in enumerate(outputs):
                if output.devicename.rstrip("\0").casefold() != device.casefold():
                    continue
                coords = output.desc.DesktopCoordinates
                rect = (coords.left, coords.top, coords.right, coords.bottom)
                if rect == monitor_rect:
                    return device_idx, output_idx
        raise RuntimeError("Monitor not available in DXCAM; using BitBlt.")

    def _prepare_dxcam(self):
        import dxcam  # Already initialized on the main thread for DXCAM mode.

        key = (self.device_idx, self.output_idx)
        region = self.region
        if self.desktop_coordinates and region is not None:
            monitor = win32api.MonitorFromRect(region, 2)  # MONITOR_DEFAULTTONEAREST
            info = win32api.GetMonitorInfo(monitor)
            ml, mt, mr, mb = info["Monitor"]
            left, top, right, bottom = region
            if not (ml <= left < right <= mr and mt <= top < bottom <= mb):
                # GDI can capture windows spanning outputs, unlike a single DXCamera.
                return None
            key = self._resolve_dxcam_output(dxcam, info["Device"], tuple(info["Monitor"]))
            region = (left - ml, top - mt, right - ml, bottom - mt)

        if self.camera is None or self._camera_key != key:
            self._release_camera()
            self.camera = dxcam.create(
                device_idx=key[0], output_idx=key[1], output_color=self.output_color,
            )
            self._camera_key = key
        return region

    def _capture_dxcam(self):
        try:
            region = self._prepare_dxcam()
            if self.desktop_coordinates and self.region is not None and region is None:
                return self._capture_bitblt()
            # grab() returns None on an unchanged desktop. Do not call the blocking
            # get_latest_frame() unless the asynchronous capture loop was started.
            return self.camera.grab(region=region)
        except Exception as exc:
            print(f"DXCAM unavailable: {exc}. Falling back to BitBlt.")
            self._release_camera()
            self.mode = "bitblt"
            return self._capture_bitblt()

    def _init_bitblt_resources(self, width, height):
        self._cleanup_gdi()
        # Screen DC uses virtual-desktop coordinates, including negative origins.
        self._hwnd_dc = win32gui.GetDC(0)
        self._mfc_dc = win32ui.CreateDCFromHandle(self._hwnd_dc)
        self._save_dc = self._mfc_dc.CreateCompatibleDC()
        self._save_bitmap = win32ui.CreateBitmap()
        self._save_bitmap.CreateCompatibleBitmap(self._mfc_dc, width, height)
        self._save_dc.SelectObject(self._save_bitmap)
        self._last_dims = (width, height)

    def _cleanup_gdi(self):
        # Deselect bitmap before deletion
        if self._save_dc:
            try:
                # Selecting a small dummy bitmap or 0 can help deselect the current one
                # but in win32ui it's often safer to just try/except the deletion
                self._save_dc.DeleteDC()
            except:
                pass
            self._save_dc = None
            
        if self._mfc_dc:
            try:
                self._mfc_dc.DeleteDC()
            except:
                pass
            self._mfc_dc = None
            
        if self._hwnd_dc:
            try:
                win32gui.ReleaseDC(0, self._hwnd_dc)
            except:
                pass
            self._hwnd_dc = None
            
        if self._save_bitmap:
            try:
                win32gui.DeleteObject(self._save_bitmap.GetHandle())
            except:
                pass
            self._save_bitmap = None

    def _capture_bitblt(self):
        """
        Ultra-fast GDI Capture using GetDIBits and raw memory access.
        """
        try:
            if self.region is None:
                width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                left, top = 0, 0
            else:
                left, top, right, bottom = self.region
                width = right - left
                height = bottom - top

            if width <= 0 or height <= 0: return None

            if (width, height) != self._last_dims or self._save_dc is None:
                self._init_bitblt_resources(width, height)

            # 1. BitBlt to our compatible DC
            self._save_dc.BitBlt((0, 0), (width, height), self._mfc_dc, (left, top), win32con.SRCCOPY)
            
            # 2. Extract bits directly to a pre-allocated numpy array for speed
            # GetBitmapBits is very slow. GetDIBits is preferred but win32ui's GetBitmapBits 
            # is often a wrapper. Let's use the fastest possible way.
            # signedIntsArray = self._save_bitmap.GetBitmapBits(True) # This is a slow copy
            
            # Optimization: Use the fact that Pygame can read BGRA directly
            # and that we can avoid cv2.cvtColor by just reversing the last channel if needed
            # For now, let's use the buffer and reshape.
            # Note: We keep RGBA to avoid cvtColor.
            
            data = self._save_bitmap.GetBitmapBits(True)
            img = np.frombuffer(data, dtype='uint8')
            img.shape = (height, width, 4)
            
            # Return RGB (discard alpha and flip BGR if necessary)
            # This slice is much faster than cv2.cvtColor
            # We use .copy() to ensure the array is contiguous for Pygame frombuffer
            return img[:, :, :3][:, :, ::-1].copy() 
            
        except Exception as e:
            self._cleanup_gdi()
            return None

    def start_high_speed_capture(self, target_fps=60):
        """
        Starts a continuous capture loop.
        """
        if self.mode != "dxcam":
            raise RuntimeError("High-speed capture requires DXCAM.")
        region = self._prepare_dxcam()
        if self.desktop_coordinates and self.region is not None and region is None:
            raise ValueError("DXCAM high-speed capture requires a region inside one monitor.")
        self.camera.start(target_fps=target_fps, region=region)
        self.is_capturing = True
        print(f"Started DXCAM capture at {target_fps} FPS")

    def get_latest_frame(self):
        return self.camera.get_latest_frame()

    def _release_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self._camera_key = None
        self.is_capturing = False

    def stop_capture(self):
        try:
            self._release_camera()
        finally:
            self._cleanup_gdi()

if __name__ == "__main__":
    # Test capture
    cap = ScreenCapture(mode="bitblt")
    print("Testing BitBlt speed for 100 frames with persistent GDI...")
    start_time = time.time()
    count = 0
    while count < 100:
        frame = cap.capture_frame()
        if frame is not None:
            count += 1
    end_time = time.time()
    print(f"Captured 100 frames in {end_time - start_time:.4f} seconds")
    print(f"Effective FPS: {100 / (end_time - start_time):.2f}")
    
    # Show one frame to verify
    frame = cap.capture_frame()
    if frame is not None:
        cv2.imwrite("test_capture_bitblt.jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        print("Test frame saved to test_capture_bitblt.jpg")
    cap.stop_capture()
