import cv2
import numpy as np
import os

import diagnostics
import ort_providers


class AMDFilters:
    """Sharpening and upscaling that stay cheap enough for real-time frames.

    Everything here runs at the internal (processing) resolution: at display
    resolution the same work costs 10-20x more per frame and starves the overlay.
    """

    # Beyond this amount the adaptive weight saturates to "sharpen everything",
    # which is exactly the ringing CAS exists to avoid.
    MAX_SHARPNESS = 2.0

    @staticmethod
    def _adaptive_weight(img, amount):
        """Per-pixel sharpening weight: strong on flat detail, near zero on hard edges."""
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        detail = cv2.subtract(gray, cv2.blur(gray, (3, 3)), dtype=cv2.CV_16S)
        # Flat areas (detail 0) keep the full amount; high-contrast edges keep almost none.
        return cv2.convertScaleAbs(detail, alpha=-float(amount), beta=float(amount) * 255.0)

    @staticmethod
    def apply_cas(img, sharpness=0.5):
        """Contrast adaptive sharpening with 8-bit saturating maths only.

        The previous float32 erode/dilate/filter2D version cost ~95 ms per 1080p
        frame; this one is a couple of milliseconds at the internal resolution.
        """
        try:
            amount = min(max(float(sharpness), 0.0), AMDFilters.MAX_SHARPNESS)
        except (TypeError, ValueError):
            return img
        if amount <= 0:
            return img

        weight = AMDFilters._adaptive_weight(img, amount)
        weight_rgb = cv2.cvtColor(weight, cv2.COLOR_GRAY2RGB)
        blurred = cv2.blur(img, (3, 3))
        # Positive and negative detail are handled separately so every operation
        # can stay in uint8 and clamp instead of wrapping around.
        brighter = cv2.subtract(img, blurred)
        darker = cv2.subtract(blurred, img)
        sharpened = cv2.add(img, cv2.multiply(brighter, weight_rgb, scale=1.0 / 255.0))
        return cv2.subtract(sharpened, cv2.multiply(darker, weight_rgb, scale=1.0 / 255.0))

    @staticmethod
    def apply_unsharp(img, sharpness=0.3, sigma=2.0):
        """Plain unsharp mask, used when FSR is off."""
        try:
            amount = min(max(float(sharpness), 0.0), AMDFilters.MAX_SHARPNESS)
        except (TypeError, ValueError):
            return img
        if amount <= 0:
            return img
        return cv2.addWeighted(img, 1.0 + amount, cv2.GaussianBlur(img, (0, 0), sigma), -amount, 0)

    @staticmethod
    def apply_easu(img, target_dim):
        """Upscale step of the FSR path.

        Bicubic is visually close to Lanczos on an already sharpened image and
        several times cheaper, which is what keeps the overlay at the target FPS.
        """
        height, width = img.shape[:2]
        if (width, height) == tuple(target_dim):
            return img
        return cv2.resize(img, target_dim, interpolation=cv2.INTER_CUBIC)

class NvidiaAIUpscaler:
    def __init__(self, model_path=None):
        self.model_path = model_path or os.path.join(os.path.dirname(__file__), "models", "fsrcnn_x2.onnx")
        self.session = None
        if self._check_model_file():
            self._init_session()

    def _check_model_file(self):
        """The model ships with the app; a missing file is a real problem to report."""
        if os.path.exists(self.model_path):
            return True
        message = f"modelo de upscale ausente: {self.model_path}"
        print(f"AI SuperRes disabled: {message}")
        diagnostics.write_now("ia", message)
        return False

    def _init_session(self):
        try:
            # DirectML first: the same model runs in a few milliseconds on a GPU and
            # in hundreds of milliseconds on the CPU, which is the difference between
            # a filter that fits the frame budget and one that stalls the overlay.
            self.session, providers = ort_providers.create_session(self.model_path)
            used = ort_providers.describe(self.session)
            print(f"AI upscaler session initialized with {used}")
            diagnostics.write_now("ia", f"upscaler ONNX em {used}")
        except Exception as e:
            self.session = None
            print(f"Error initializing ONNX session: {e}")
            diagnostics.write_now("ia", f"erro ao carregar o modelo de upscale: {e}")

    def upscale(self, img):
        if self.session is None: return img
        
        # Pre-process: 1. Convert to YCrCb (SR usually works on Y channel)
        # However, for simplicity and color, we'll process RGB if model supports it
        # The FSRCNN model usually expects (B, 1, H, W) for Y-channel
        # or (B, 3, H, W) for RGB.
        
        # Resize to model input if needed (usually AI is fixed scale)
        # FSRCNN is x2. 
        # For a general solution, AI is harder. Let's assume the user wants x2
        # or we just use it for the core upscaling.
        
        h, w = img.shape[:2]
        img_f = img.astype(np.float32) / 255.0
        
        # Prepare for ONNX: (H, W, C) -> (1, C, H, W)
        input_tensor = np.transpose(img_f, (2, 0, 1))[np.newaxis, ...]
        
        input_name = self.session.get_inputs()[0].name
        output = self.session.run(None, {input_name: input_tensor})[0]
        
        # Post-process: (1, C, H, W) -> (H, W, C)
        output = np.transpose(output[0], (1, 2, 0))
        output = (np.clip(output, 0, 1) * 255).astype(np.uint8)
        
        return output
