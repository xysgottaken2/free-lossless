import cv2
import numpy as np
import time
import os
import requests

import diagnostics
import ort_providers


class RIFEEngine:
    def __init__(self, model_version="rife-v4"):
        """
        Using OpenCV DISOpticalFlow as a fast fallback that works in real-time.
        """
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
        self.dis.setFinestScale(1)
        self.dis.setGradientDescentIterations(10)
        self.dis.setVariationalRefinementIterations(0) # Disable for speed
        
        self.last_h = 0
        self.last_w = 0
        self.map_x = None
        self.map_y = None
        self.high_precision = False
        
        print("Optimized Optical Flow Engine (DIS ULTRAFAST) initialized.")

    def set_high_precision(self, enabled):
        self.high_precision = enabled
        if enabled:
            # Ultra Smooth Mode: Higher precision, way more CPU usage
            self.dis.setFinestScale(0) # 0 is finer than 1
            self.dis.setGradientDescentIterations(25)
            self.dis.setVariationalRefinementIterations(5)
            print("Engine set to ULTRA SMOOTH (High Precision)")
        else:
            # Standard Mode: Fast and efficient
            self.dis.setFinestScale(1)
            self.dis.setGradientDescentIterations(10)
            self.dis.setVariationalRefinementIterations(0)
            print("Engine set to STANDARD Precision")

    def interpolate(self, frame1, frame2, timestep=0.5):
        """
        Interpolate between frame1 and frame2 using stabilized bilateral warping.

        ``timestep`` positions the result between both frames (0 = frame1, 1 = frame2),
        which allows generating several intermediate frames per captured pair.
        """
        if frame1.shape != frame2.shape:
            return frame2
        timestep = min(1.0, max(0.0, float(timestep)))

        h, w = frame1.shape[:2]
        
        # 1. Quick static check
        if np.array_equal(frame1[::100, ::100], frame2[::100, ::100]):
            return frame1

        # 2. Prepare Grayscale
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_RGB2GRAY)
        
        # 3. Low-res flow calculation
        scale = 0.25
        small1 = cv2.resize(gray1, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        small2 = cv2.resize(gray2, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        
        flow = self.dis.calc(small1, small2, None)
        
        # 4. Stabilize Flow (Advanced Filtering)
        # Median filter removes outliers, Gaussian smooths transitions
        flow = cv2.medianBlur(flow, 3)
        flow = cv2.GaussianBlur(flow, (3, 3), 0.5)
        
        # 5. Advanced UI & Text Shield (Protection Mask)
        # a) Static Check: regions that don't change between frames
        diff = cv2.absdiff(small1, small2)
        # Better thresholding for static areas
        _, static_mask = cv2.threshold(diff, 8, 1.0, cv2.THRESH_BINARY_INV)
        static_mask = static_mask.astype(np.float32)
        
        # b) Edge Check (Motion Boundary Detection): 
        # Strong edges in the original frame often shouldn't warp too much if they are UI
        edges = cv2.Canny(small1, 50, 150)
        edge_mask = np.clip(edges.astype(np.float32) / 255.0, 0, 1)
        
        # Combine: protect if it's static OR has strong edge density (typical of HUDs)
        # We use a soft mask to avoid harsh transitions
        protection_mask = np.maximum(static_mask, edge_mask)
        protection_mask = cv2.dilate(protection_mask, np.ones((3, 3), np.uint8))
        protection_mask = cv2.GaussianBlur(protection_mask, (5, 5), 0)

        # Motion magnitude, also at the small scale: 16x cheaper than at full
        # resolution and the mask is smoothed anyway.
        small_mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        # 0 = pure warp, 0.4 = mix with a cross-fade where motion is extreme.
        small_blend = np.clip(small_mag / 30.0, 0.0, 1.0) * 0.4

        # Dampen flow: 0 flow in protected areas
        flow *= (1.0 - protection_mask)[..., np.newaxis]

        # 6. Scale and resize flow
        flow = flow * (1.0 / scale)
        flow = cv2.resize(flow, (w, h), interpolation=cv2.INTER_CUBIC) # Cubic for smoother upscaling
        
        # 7. Bilateral Warping Logic
        if h != self.last_h or w != self.last_w:
            self.map_x, self.map_y = np.meshgrid(np.arange(w), np.arange(h))
            self.map_x = self.map_x.astype(np.float32)
            self.map_y = self.map_y.astype(np.float32)
            self.last_h, self.last_w = h, w
        
        # Forward warp map (frame1 -> intermediate frame)
        m1_x = self.map_x + flow[..., 0] * timestep
        m1_y = self.map_y + flow[..., 1] * timestep
        
        # Backward warp map (frame2 -> intermediate frame)
        m2_x = self.map_x - flow[..., 0] * (1.0 - timestep)
        m2_y = self.map_y - flow[..., 1] * (1.0 - timestep)
        
        # Warp both
        inter1 = cv2.remap(frame1, m1_x, m1_y, cv2.INTER_LINEAR)
        inter2 = cv2.remap(frame2, m2_x, m2_y, cv2.INTER_LINEAR)
        
        # Weighted combination: in low motion the warped frames win; in extreme
        # motion the mask mixes in a cross-fade to hide artifacts.
        combined = cv2.addWeighted(inter1, 1.0 - timestep, inter2, timestep, 0)
        
        # Everything below stays in uint8: the float32 version allocated several
        # full-resolution temporaries and cost more than the flow itself.
        blend_mask = cv2.resize(small_blend, (w, h), interpolation=cv2.INTER_LINEAR)
        weight = cv2.convertScaleAbs(blend_mask, alpha=255.0)
        if cv2.countNonZero(weight) == 0:
            return combined
        weight_rgb = cv2.cvtColor(weight, cv2.COLOR_GRAY2RGB)
        cross_fade = cv2.addWeighted(frame1, 1.0 - timestep, frame2, timestep, 0)
        inverse = cv2.bitwise_not(weight_rgb)  # 255 - weight, in place of a subtraction
        return cv2.add(cv2.multiply(combined, inverse, scale=1.0 / 255.0),
                       cv2.multiply(cross_fade, weight_rgb, scale=1.0 / 255.0))


class RIFEONNXEngine:
    def __init__(self, model_path=None):
        self.model_path = model_path or os.path.join(os.path.dirname(__file__), "models", "rife_v4_lite.onnx")
        self.session = None
        self.last_h = 0
        self.last_w = 0
        
        # Download if missing
        self._download_model_if_missing()
        self._init_session()
        
    def _download_model_if_missing(self):
        # Delete if corrupted (too small)
        if os.path.exists(self.model_path) and os.path.getsize(self.model_path) < 1000:
            print(f"Deleting corrupted model at {self.model_path}")
            os.remove(self.model_path)

        if not os.path.exists(self.model_path):
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            print(f"Downloading RIFE AI model to {self.model_path}...")
            # Using a more reliable HuggingFace source
            url = "https://huggingface.co/tensorstack/RIFE/resolve/main/model.onnx?download=true"
            try:
                r = requests.get(url, allow_redirects=True, timeout=60, stream=True)
                r.raise_for_status()
                with open(self.model_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                print("RIFE Model downloaded successfully.")
            except Exception as e:
                print(f"Failed to download RIFE model: {e}")

    def _init_session(self):
        try:
            import onnxruntime as ort
            # DirectML (every Windows GPU), then CUDA, then the CPU.
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.session, providers = ort_providers.create_session(self.model_path, sess_options)
            used = ort_providers.describe(self.session)
            print(f"RIFE Inference session initialized with: {used}")
            diagnostics.write_now("motor", f"RIFE ONNX em {used}")
            if not ort_providers.is_gpu(providers):
                print("WARNING: RIFE is running on CPU. Performance will be low.")
                print("HINT: Install 'onnxruntime-directml' for GPU acceleration on Windows.")
                diagnostics.write_now("motor", "RIFE rodando na CPU (sem DirectML/CUDA)")
        except Exception as e:
            print(f"Error initializing RIFE ONNX session: {e}")
            diagnostics.write_now("motor", f"erro ao iniciar o RIFE: {e}")

    def interpolate(self, frame1, frame2, timestep=0.5):
        if self.session is None:
            return frame2
        timestep = min(1.0, max(0.0, float(timestep)))
        time_array = np.array([timestep], dtype=np.float32)
            
        h, w = frame1.shape[:2]
        
        # RIFE usually requires multiples of 32 or 64. 
        # We'll pad/resize if needed, or assume internal_res is already compatible.
        # For simplicity, let's just resize to 512x512 for now or keep original if it works.
        # Most lite models are trained on specific resolutions or are flexible.
        
        # Pre-process: RGB [0, 255] -> [0, 1] and (H, W, C) -> (1, C, H, W)
        img1 = (frame1.astype(np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis, ...]
        img2 = (frame2.astype(np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis, ...]
        
        # Prepare for RIFE (img0, img1, timestep)
        # We need to map our inputs to what the model expects
        input_dict = {
            "img0": img1,
            "img1": img2,
            "timestep": time_array
        }
        
        try:
            # Run inference
            output = self.session.run(None, input_dict)[0]
            
            # Post-process: (1, C, H, W) -> (H, W, C) [0, 255]
            res = (np.clip(output[0].transpose(1, 2, 0), 0, 1) * 255).astype(np.uint8)
            return res
        except Exception:
            # Fallback if names are slightly different or model varies
            try:
                # Dynamic mapping if names changed
                inputs = [i.name for i in self.session.get_inputs()]
                alt_dict = {
                    inputs[0]: img1,
                    inputs[1]: img2
                }
                if len(inputs) > 2:
                    alt_dict[inputs[2]] = time_array
                output = self.session.run(None, alt_dict)[0]
                res = (np.clip(output[0].transpose(1, 2, 0), 0, 1) * 255).astype(np.uint8)
                return res
            except Exception as e2:
                print(f"Interpolation error: {e2}")
                return frame2

if __name__ == "__main__":
    # Test engine
    engine = RIFEEngine()
    # To test RIFE:
    # engine = RIFEONNXEngine()
    f1 = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.circle(f1, (100, 100), 50, (255, 0, 0), -1)
    f2 = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.circle(f2, (200, 100), 50, (255, 0, 0), -1)
    
    print("Testing interpolation...")
    for step in (0.25, 0.5, 0.75):
        start = time.time()
        result = engine.interpolate(f1, f2, timestep=step)
        end = time.time()
        print(f"t={step}: {end - start:.4f} seconds ({1/(end-start):.2f} FPS)")
        cv2.imwrite(f"test_inter_{int(step * 100)}.jpg", cv2.cvtColor(result, cv2.COLOR_RGB2BGR))
