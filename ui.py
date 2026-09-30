"""Free Lossless main window (tkinter).

Layout (the Start/Stop bar is packed FIRST so it is always visible):

    +----------------------------------------------------------+
    |  Free Lossless - Frame Generation                        |
    |  instructions (1-2-3) + hotkeys                          |
    +----------------------------------------------------------+
    |  Capture Source: [Window / Full Screen]                  |
    |  Window list   OR   Monitor: [Display 1 (Primary)]       |
    +----------------------------------------------------------+
    |  scrollable settings: backend / fps / scale / algo /     |
    |  RIFE engine / DLSS 5 optional panel                     |
    |  ...                                                     |
    +----------------------------------------------------------+
    |  Status: Stopped                                         |
    |  [                    Start                    ]         |
    +----------------------------------------------------------+

All user-facing strings are in plain English (matching the console output
and the README).  ``collect_selection()`` returns the same selection keys the
pipeline has always consumed (mode/fps/scale/algo/fg_enabled/sharpness/...)
plus the new ``source`` and ``monitor`` keys for Full Screen capture.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from config import AppConfig

try:
    from selector import WindowSelector
except Exception:  # win32 not available (dev machines / Linux CI)
    class WindowSelector:  # minimal stub so the UI can be tested headless
        @staticmethod
        def get_visible_windows():
            return []

        @staticmethod
        def get_window_rect(hwnd):
            raise RuntimeError("win32 window enumeration is not available")

from targets import (
    SOURCE_FULLSCREEN,
    SOURCE_LABELS,
    SOURCE_VALUES,
    SOURCE_WINDOW,
    list_monitors,
    normalize_source,
)
from ui_status import build_dlss5_status_lines, describe_runtime


class GameSelectorUI:
    """Main window: capture source picker + settings + Start/Stop bar."""

    def __init__(self, app_config=None):
        self.app_config = app_config if app_config is not None else AppConfig()
        self.selector = WindowSelector()
        self._controller = None
        self._monitors = list_monitors()

        self.root = tk.Tk()
        self.root.title("Free Lossless - Frame Generation")
        self.root.geometry("780x880")
        self.root.minsize(640, 620)
        self.root.resizable(True, True)

        # ---- 1) Fixed bottom bar FIRST (Status + big Start/Stop) --------
        self.bottom_bar = tk.Frame(self.root, pady=8)
        self.bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = ttk.Label(
            self.bottom_bar, text="Status: Stopped", font=("Arial", 11, "bold")
        )
        self.status_label.pack(anchor="w", padx=12)

        self.start_button = tk.Button(
            self.bottom_bar,
            text="Start",
            font=("Arial", 13, "bold"),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049",
            pady=6,
        )
        self.start_button.pack(fill=tk.X, padx=12, pady=(6, 0))

        # ---- 2) Header + instructions -----------------------------------
        header = tk.Frame(self.root, pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="Free Lossless - Frame Generation",
            font=("Arial", 14, "bold"), fg="#2196F3",
        ).pack()

        instr_text = (
            "Instructions:\n"
            "1. Pick a capture source: Window (one app) or Full Screen (the whole monitor).\n"
            "2. In Window mode select the window below; in Full Screen mode pick the monitor.\n"
            "3. Adjust Target FPS and quality options, then press Start.\n"
            "   Press Stop (or F11) to return to this window.\n"
            "\n"
            "Global Hotkeys (while running):\n"
            "  [F9]  Toggle FSR sharpening filter\n"
            "  [F10] Show/Hide FPS counter\n"
            "  [F11] Stop and return here"
        )
        tk.Label(
            header, text=instr_text, justify=tk.LEFT, font=("Arial", 9),
            fg="#555", padx=20,
        ).pack(anchor="w")

        # ---- 3) Capture source ------------------------------------------
        source_frame = tk.LabelFrame(self.root, text="Capture Source", pady=5, padx=10)
        source_frame.pack(fill=tk.X, padx=10, pady=5)

        source_row = tk.Frame(source_frame)
        source_row.pack(fill=tk.X)
        tk.Label(source_row, text="Capture Mode:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.source_combo = ttk.Combobox(
            source_row,
            values=[SOURCE_LABELS[s] for s in SOURCE_VALUES],
            state="readonly", width=14,
        )
        self.source_combo.pack(side=tk.LEFT, padx=8)
        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_changed)

        # Window picker (Window mode)
        self.window_frame = tk.Frame(source_frame)
        win_row = tk.Frame(self.window_frame)
        win_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(win_row, text="Detected Windows:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.refresh_button = tk.Button(win_row, text="Refresh List", command=self._refresh_list)
        self.refresh_button.pack(side=tk.RIGHT)

        self.tree = ttk.Treeview(
            self.window_frame, columns=("Title", "Process"), show="headings", height=7
        )
        self.tree.heading("Title", text="Window Title")
        self.tree.heading("Process", text="Process")
        self.tree.column("Title", width=380)
        self.tree.column("Process", width=150)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # Monitor picker (Full Screen mode)
        self.monitor_frame = tk.Frame(source_frame)
        monitor_row = tk.Frame(self.monitor_frame)
        monitor_row.pack(fill=tk.X, pady=(8, 0))
        tk.Label(monitor_row, text="Monitor:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        monitor_labels = [m.label for m in self._monitors] or ["Display 1 (Primary)"]
        self.monitor_combo = ttk.Combobox(
            monitor_row, values=monitor_labels, state="readonly", width=32
        )
        self.monitor_combo.pack(side=tk.LEFT, padx=8)
        self.monitor_combo.current(0)
        self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_changed)

        # ---- 4) Scrollable settings -------------------------------------
        settings = self._make_scrollable(self.root)

        mode_frame = tk.Frame(settings, pady=5)
        mode_frame.pack(fill=tk.X, padx=10)
        tk.Label(mode_frame, text="Capture Backend:").grid(row=0, column=0)
        self.mode_var = tk.StringVar(value="dxcam")
        self.mode_combo = ttk.Combobox(
            mode_frame, textvariable=self.mode_var,
            values=["dxcam", "bitblt"], state="readonly", width=10,
        )
        self.mode_combo.grid(row=0, column=1, padx=5)

        fps_frame = tk.Frame(settings, pady=5)
        fps_frame.pack(fill=tk.X, padx=10)
        tk.Label(fps_frame, text="Target FPS:").grid(row=0, column=0)
        self.fps_var = tk.IntVar(value=60)
        self.fps_scale = tk.Scale(
            fps_frame, from_=30, to=120, orient=tk.HORIZONTAL,
            variable=self.fps_var, resolution=1, length=220,
        )
        self.fps_scale.grid(row=0, column=1, padx=5)

        scale_frame = tk.Frame(settings, pady=5)
        scale_frame.pack(fill=tk.X, padx=10)
        tk.Label(scale_frame, text="Display Scale:").grid(row=0, column=0)
        self.scale_var = tk.StringVar(value="1.0")
        self.scale_combo = ttk.Combobox(
            scale_frame, textvariable=self.scale_var,
            values=["1.0", "1.25", "1.5", "2.0", "Fullscreen"],
            state="readonly", width=12,
        )
        self.scale_combo.grid(row=0, column=1, padx=5)

        algo_frame = tk.Frame(settings, pady=5)
        algo_frame.pack(fill=tk.X, padx=10)
        tk.Label(algo_frame, text="Upscale Algorithm / FSR:").grid(row=0, column=0)
        self.algo_var = tk.StringVar(value="Lanczos")
        self.algo_combo = ttk.Combobox(
            algo_frame, textvariable=self.algo_var,
            values=[
                "Bilinear", "Bicubic", "Lanczos",
                "FSR 1.0 / CAS (Sharpening)", "NVIDIA AI SuperRes",
            ],
            state="readonly", width=22,
        )
        self.algo_combo.grid(row=0, column=1, padx=5)

        fg_frame = tk.Frame(settings, pady=5)
        fg_frame.pack(fill=tk.X, padx=10)
        self.fg_var = tk.BooleanVar(value=True)
        self.fg_check = tk.Checkbutton(
            fg_frame, text="Frame Generation (RIFE)", variable=self.fg_var
        )
        self.fg_check.grid(row=0, column=0)
        self.engine_var = tk.StringVar(value="AI (RIFE ONNX)")
        self.engine_combo = ttk.Combobox(
            fg_frame, textvariable=self.engine_var,
            values=["AI (RIFE ONNX)", "Fast (DIS Flow)"],
            state="readonly", width=15,
        )
        self.engine_combo.grid(row=0, column=1, padx=5)

        adv_frame = tk.Frame(settings, pady=5)
        adv_frame.pack(fill=tk.X, padx=10)
        self.ultra_smooth_var = tk.BooleanVar(value=False)
        self.ultra_smooth_check = tk.Checkbutton(
            adv_frame, text="Ultra Smooth (Higher Precision)", variable=self.ultra_smooth_var
        )
        self.ultra_smooth_check.grid(row=0, column=0, padx=5)
        self.perf_mode_var = tk.BooleanVar(value=False)
        self.perf_mode_check = tk.Checkbutton(
            adv_frame, text="Performance Mode", variable=self.perf_mode_var
        )
        self.perf_mode_check.grid(row=0, column=1, padx=5)
        self.low_latency_var = tk.BooleanVar(value=True)
        self.low_latency_check = tk.Checkbutton(
            adv_frame, text="Low Latency (Minimal Buffer)", variable=self.low_latency_var
        )
        self.low_latency_check.grid(row=1, column=0, columnspan=2, pady=5)

        sharp_frame = tk.Frame(settings, pady=5)
        sharp_frame.pack(fill=tk.X, padx=10)
        tk.Label(sharp_frame, text="Sharpening:").grid(row=0, column=0)
        self.sharp_var = tk.IntVar(value=20)
        self.sharp_scale = tk.Scale(
            sharp_frame, from_=0, to=100, orient=tk.HORIZONTAL,
            variable=self.sharp_var, resolution=1, length=220,
        )
        self.sharp_scale.grid(row=0, column=1, padx=5)

        # ----- DLSS 5 Neural Rendering (optional stage before RIFE) -----
        self._setup_dlss5_panel(settings)

        # ---- 5) Source default / initial refresh -------------------------
        saved_source = SOURCE_WINDOW
        try:
            saved_source = normalize_source(self.app_config.capture.get("source", SOURCE_WINDOW))
        except Exception:
            pass
        self.source_combo.current(0 if saved_source == SOURCE_WINDOW else 1)
        try:
            saved_monitor = int(self.app_config.capture.get("monitor", 0))
        except (TypeError, ValueError):
            saved_monitor = 0
        if self._monitors:
            saved_monitor = max(0, min(len(self._monitors) - 1, saved_monitor))
            self.monitor_combo.current(saved_monitor)

        self._apply_source_mode()
        self._refresh_list()

    # ------------------------------------------------------------------ UI
    def _make_scrollable(self, parent):
        container = tk.Frame(parent)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(inner_window, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        return inner

    def bind_controller(self, controller) -> None:
        self._controller = controller
        self.start_button.configure(command=controller.on_button_clicked)
        self.root.protocol("WM_DELETE_WINDOW", controller.on_close)

    def show_state(self, button_text: str, status_text: str) -> None:
        self.start_button.configure(text=button_text)
        self.status_label.configure(text=status_text)
        self.process_events()

    def process_events(self) -> None:
        try:
            self.root.update()
        except tk.TclError:
            pass

    def mainloop(self) -> None:
        self.root.mainloop()

    def destroy(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # --------------------------------------------------------- capture source
    def selected_source(self) -> str:
        label = self.source_combo.get()
        for source, source_label in SOURCE_LABELS.items():
            if source_label == label:
                return source
        return normalize_source(label)

    def is_fullscreen(self) -> bool:
        return self.selected_source() == SOURCE_FULLSCREEN

    def _persist_capture_source(self):
        try:
            self.app_config.capture["source"] = self.selected_source()
            self.app_config.capture["monitor"] = int(self.monitor_combo.current() or 0)
            self.app_config.save()
        except Exception as exc:
            print(f"[CONFIG] Could not save capture source: {exc}")

    def _on_source_changed(self, _event=None) -> None:
        self._apply_source_mode()
        self._persist_capture_source()

    def _on_monitor_changed(self, _event=None) -> None:
        self._persist_capture_source()

    def _apply_source_mode(self) -> None:
        if self.is_fullscreen():
            self.window_frame.pack_forget()
            self.monitor_frame.pack(fill=tk.X)
        else:
            self.monitor_frame.pack_forget()
            self.window_frame.pack(fill=tk.BOTH, expand=True)

    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            windows = self.selector.get_visible_windows()
        except Exception as exc:
            print(f"[UI] Could not enumerate windows: {exc}")
            return
        for w in windows:
            self.tree.insert("", tk.END, values=(w["title"], w["process"]), iid=str(w["hwnd"]))

    def collect_selection(self):
        """Return the selection dict for the pipeline, or None if incomplete."""
        selection = {
            "source": self.selected_source(),
            "mode": self.mode_var.get(),
            "fps": int(self.fps_var.get()),
            "scale": self.scale_var.get(),
            "algo": self.algo_var.get(),
            "sharpness": int(self.sharp_var.get()),
            "fg_enabled": bool(self.fg_var.get()),
            "engine_type": self.engine_var.get(),
            "ultra_smooth": bool(self.ultra_smooth_var.get()),
            "performance_mode": bool(self.perf_mode_var.get()),
            "low_latency": bool(self.low_latency_var.get()),
            "dlss5_enabled": bool(self.dlss5_var.get()),
            "dlss5_intensity": float(self.dlss5_intensity_var.get()),
            "dlss5_style": int(self.dlss5_style_var.get()),
            "dlss5_passes": int(self.dlss5_passes_var.get()),
            "dlss5_work_scale": float(self.dlss5_work_scale_var.get()),
            "dlss5_auto_mask": bool(self.dlss5_auto_mask_var.get()),
        }

        if self.is_fullscreen():
            index = self.monitor_combo.current()
            selection["monitor"] = index if index >= 0 else 0
            selection["title"] = self.monitor_combo.get()
            self._persist_capture_source()
            return selection

        selected = self.tree.selection()
        if not selected:
            return None
        selection["hwnd"] = int(selected[0])
        selection["title"] = self.tree.item(selected[0], "values")[0]
        return selection

    # -------------------------------------------------------------- DLSS 5
    def _setup_dlss5_panel(self, parent):
        """Optional DLSS 5 Neural Rendering stage controls + live status."""
        cfg = None
        if self.app_config is not None:
            cfg = self.app_config.dlss5

        dlss_frame = tk.LabelFrame(parent, text="DLSS 5 Neural Rendering (optional)", pady=5, padx=10)
        dlss_frame.pack(fill=tk.X, padx=10, pady=5)

        self.dlss5_var = tk.BooleanVar(value=bool(cfg.get("enabled", False)) if cfg else False)
        self.dlss5_check = tk.Checkbutton(
            dlss_frame,
            text="Enable DLSS 5 Neural Rendering",
            variable=self.dlss5_var,
        )
        self.dlss5_check.grid(row=0, column=0, columnspan=2, sticky="w")

        # Status block: Runtime / GPU / Backend / Status
        self._dlss5_status = {}
        status_box = tk.Frame(dlss_frame)
        status_box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 2))
        try:
            from neural.runtime import RuntimeLocator
            from neural.system_info import query_gpu_name, query_display_driver_version

            report = RuntimeLocator().report()
            runtime_text = describe_runtime(report.dlssnr.present, report.dlssnr.version)
            gpu_text = query_gpu_name()
            driver_text = query_display_driver_version()
            backend_text = "ngx-core+dlssnr" if report.dlssnr.present and report.bridge else "none"
            status_text = "Ready to probe" if report.dlssnr.present and report.bridge else "Disabled (runtime/bridge not found)"
        except Exception as e:
            runtime_text, gpu_text, driver_text = "Not Found", "unknown", "unknown"
            backend_text, status_text = "none", f"Disabled ({e})"
        lines = build_dlss5_status_lines(runtime_text, gpu_text, backend_text, status_text)
        for i, line in enumerate(lines):
            label = tk.Label(status_box, text=line, font=("Consolas", 9), fg="#333", anchor="w")
            label.grid(row=i, column=0, sticky="w")
            self._dlss5_status[i] = label
        if driver_text and driver_text != "unknown":
            tk.Label(status_box, text=f"Driver: {driver_text}", font=("Consolas", 9), fg="#666", anchor="w").grid(row=4, column=0, sticky="w")

        # Controls confirmed against the real DLSSNR runtime contract
        # (Intensity/Style/Passes/processing-scale; see docs/dlss5-research.md).
        ctrl = tk.Frame(dlss_frame)
        ctrl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        tk.Label(ctrl, text="Intensity:").grid(row=0, column=0, sticky="w")
        self.dlss5_intensity_var = tk.DoubleVar(value=float(cfg.get("intensity", 0.35)) if cfg else 0.35)
        self.dlss5_intensity_scale = tk.Scale(
            ctrl, from_=0.0, to=1.0, resolution=0.01, orient=tk.HORIZONTAL,
            variable=self.dlss5_intensity_var, length=180,
        )
        self.dlss5_intensity_scale.grid(row=0, column=1, sticky="w")

        tk.Label(ctrl, text="Style (0-6):").grid(row=1, column=0, sticky="w")
        self.dlss5_style_var = tk.StringVar(value=str(int(cfg.get("style", 1)) if cfg else 1))
        self.dlss5_style_combo = ttk.Combobox(
            ctrl, textvariable=self.dlss5_style_var,
            values=[str(i) for i in range(7)], state="readonly", width=6,
        )
        self.dlss5_style_combo.grid(row=1, column=1, sticky="w")

        tk.Label(ctrl, text="Passes:").grid(row=2, column=0, sticky="w")
        self.dlss5_passes_var = tk.StringVar(value=str(int(cfg.get("passes", 1)) if cfg else 1))
        self.dlss5_passes_combo = ttk.Combobox(
            ctrl, textvariable=self.dlss5_passes_var,
            values=["1", "2"], state="readonly", width=6,
        )
        self.dlss5_passes_combo.grid(row=2, column=1, sticky="w")

        tk.Label(ctrl, text="Processing scale:").grid(row=3, column=0, sticky="w")
        self.dlss5_work_scale_var = tk.StringVar(value=str(float(cfg.get("work_scale", 1.0)) if cfg else 1.0))
        self.dlss5_work_scale_combo = ttk.Combobox(
            ctrl, textvariable=self.dlss5_work_scale_var,
            values=["1.0", "0.75", "0.5"], state="readonly", width=6,
        )
        self.dlss5_work_scale_combo.grid(row=3, column=1, sticky="w")

        self.dlss5_auto_mask_var = tk.BooleanVar(value=bool(cfg.get("auto_mask", 1)) if cfg else True)
        self.dlss5_auto_mask_check = tk.Checkbutton(
            ctrl, text="Automatic mask", variable=self.dlss5_auto_mask_var,
        )
        self.dlss5_auto_mask_check.grid(row=4, column=0, columnspan=2, sticky="w")

        tk.Label(
            dlss_frame,
            text="The runtime goes in native/ (see native/README.txt). Without it the app\n"
                 "runs on RIFE only. RTX 20 series: experimental.",
            font=("Arial", 8), fg="#777", justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))


def run_demo():
    """Small standalone demo: open the window and print the selection."""
    ui = GameSelectorUI()
    ui.start_button.configure(
        command=lambda: print(ui.collect_selection() or "Select a window first")
    )
    ui.mainloop()


if __name__ == "__main__":
    run_demo()
