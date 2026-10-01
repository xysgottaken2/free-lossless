import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import i18n
import reshade
from selector import WindowSelector, DisplaySelector
from settings import (
    ALGORITHM_OPTIONS, CAPTURE_MODES, DEFAULT_SETTINGS, DISPLAY_MODES, ENGINE_OPTIONS, FILTER_PRESETS,
    HOTKEY_OPTIONS, HOTKEY_SETTING_KEYS, MULTIPLIER_MAX,
    MULTIPLIER_MIN, MULTIPLIER_STEP, SCALE_OPTIONS, SettingsStore,
    hotkey_conflicts, normalize_settings, source_identity,
)
from theme import COLORS, draw_logo


def _t(key, **fields):
    """Translate with the language currently in effect."""
    return i18n.translate(key, **fields)


# Stored values never change; the comboboxes only show translated labels.
ALGORITHM_HINT_KEYS = {
    "Bilinear": "algo.hint.bilinear",
    "Bicubic": "algo.hint.bicubic",
    "Lanczos": "algo.hint.lanczos",
    "FSR 1.0 / CAS (Nitidez)": "algo.hint.fsr",
    "NVIDIA AI SuperRes": "algo.hint.ai",
}
DISPLAY_MODE_LABEL_KEYS = {"GDI": "display.gdi", "D3D11": "display.d3d11"}
FILTER_LABEL_KEYS = {
    "Off": "filter.off",
    "Soft": "filter.soft",
    "Sharp": "filter.sharp",
    "Vivid": "filter.vivid",
}
ALGORITHM_LABEL_KEYS = {
    "Bilinear": "algo.bilinear",
    "Bicubic": "algo.bicubic",
    "Lanczos": "algo.lanczos",
    "FSR 1.0 / CAS (Nitidez)": "algo.fsr",
    "NVIDIA AI SuperRes": "algo.ai",
}
MODE_LABEL_KEYS = {"bitblt": "mode.bitblt", "dxcam": "mode.dxcam"}
ENGINE_LABEL_KEYS = {"AI (RIFE ONNX)": "engine.rife", "Fast (DIS Flow)": "engine.fast"}


# How often the menu checks whether the ReShade download finished.
RESHADE_POLL_MS = 250


class GameSelectorUI:
    SAVE_DELAY_MS = 500
    SETTING_VARIABLES = {
        "source_type": "source_var", "mode": "mode_var", "fps": "fps_var",
        "scale": "scale_var", "algo": "algo_var", "sharpness": "sharp_var",
        "fg_enabled": "fg_var", "filters_enabled": "filters_var", "engine_type": "engine_var",
        "filter_preset": "filter_var", "display_mode": "display_mode_var",
        "ultra_smooth": "ultra_smooth_var", "performance_mode": "perf_mode_var",
        "low_latency": "low_latency_var", "frame_multiplier": "multiplier_var",
        "show_fps": "show_fps_var", "hotkey_stop": "hotkey_stop_var",
        "hotkey_fps": "hotkey_fps_var", "hotkey_fsr": "hotkey_fsr_var",
        "language": "language_var",
    }

    def __init__(self, settings_store=None):
        self.settings_store = settings_store if settings_store is not None else SettingsStore()
        settings = self.settings_store.load()
        # The saved language decides every string built below.
        i18n.set_language(settings["language"])
        self.preferred_sources = settings["preferred_sources"]
        self._last_saved_settings = normalize_settings(settings) if not self.settings_store.load_error else None
        self._save_job = None
        self._loading_settings = True
        self._closing = False
        self.selected_source = None
        self.sources = {}
        self.selector = WindowSelector()
        self.root = tk.Tk()
        self.root.title(_t("app.window_title"))
        self.root.configure(bg=COLORS["background"])
        # Scale the preferred size with Windows DPI, then fit the available display.
        self._ui_scale = max(1.0, self.root.winfo_fpixels("1i") / 96)
        width = min(round(1120 * self._ui_scale), max(720, self.root.winfo_screenwidth() - round(80 * self._ui_scale)))
        height = min(round(760 * self._ui_scale), max(480, self.root.winfo_screenheight() - round(96 * self._ui_scale)))
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(round(940 * self._ui_scale), width), min(round(620 * self._ui_scale), height))
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.root.option_add("*TCombobox*Listbox.background", COLORS["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent_dim"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", COLORS["text"])

        for key, name in self.SETTING_VARIABLES.items():
            value = settings[key]
            if isinstance(value, bool):
                variable_type = tk.BooleanVar
            elif isinstance(value, int):
                variable_type = tk.IntVar
            else:
                variable_type = tk.StringVar
            setattr(self, name, variable_type(self.root, value=value))
        self.save_status_var = tk.StringVar(self.root, value=_t("save.autosave_on"))
        self.source_count_var = tk.StringVar(self.root)
        self.selected_title_var = tk.StringVar(self.root)
        self.selected_detail_var = tk.StringVar(self.root)
        self.session_summary_var = tk.StringVar(self.root)
        self.fps_value_var = tk.StringVar(self.root)
        self.sharp_value_var = tk.StringVar(self.root)
        self.multiplier_value_var = tk.StringVar(self.root)
        self.multiplier_hint_var = tk.StringVar(self.root)
        self.shortcuts_hint_var = tk.StringVar(self.root)
        self._settings_dialog = None
        # (source variable, display variable, labels) for the translated comboboxes.
        self._choice_displays = []

        self._setup_style()
        self._setup_ui()
        self._refresh_reshade_status()
        self._refresh_list()
        self._update_setting_display()
        for name in self.SETTING_VARIABLES.values():
            getattr(self, name).trace_add("write", self._on_settings_change)
        self._loading_settings = False
        if self.settings_store.load_error:
            self._set_save_status(_t("save.unavailable"), COLORS["warning"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-Return>", self._on_select)
        self._enable_dark_titlebar()

    def _enable_dark_titlebar(self):
        if self.root.tk.call("tk", "windowingsystem") != "win32":
            return
        # Best effort: older Windows versions simply retain their native title bar.
        import ctypes
        try:
            self.root.update_idletasks()
            get_parent = ctypes.windll.user32.GetParent
            get_parent.argtypes = [ctypes.c_void_p]
            get_parent.restype = ctypes.c_void_p
            hwnd = get_parent(self.root.winfo_id()) or self.root.winfo_id()
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
                if result == 0:
                    break
        except Exception:
            # Cosmetic only: never prevent the menu from opening.
            pass

    def _setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TCombobox", fieldbackground=COLORS["input"], background=COLORS["input"],
                        foreground=COLORS["text"], arrowcolor=COLORS["muted"], bordercolor=COLORS["border"],
                        lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=8)
        style.map("App.TCombobox", fieldbackground=[("disabled", COLORS["input"]), ("readonly", COLORS["input"])],
                  background=[("active", COLORS["border"]), ("disabled", COLORS["input"])],
                  foreground=[("disabled", COLORS["muted"]), ("readonly", COLORS["text"])],
                  arrowcolor=[("disabled", COLORS["muted"]), ("active", COLORS["text"])],
                  bordercolor=[("focus", COLORS["accent"])],
                  selectbackground=[("readonly", COLORS["input"])],
                  selectforeground=[("readonly", COLORS["text"])])
        style.configure("App.Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"],
                        foreground=COLORS["text"], borderwidth=0, rowheight=round(36 * self._ui_scale), font=("Segoe UI", 10))
        style.map("App.Treeview", background=[("selected", COLORS["accent_dim"])],
                  foreground=[("selected", COLORS["text"])])
        style.configure("App.Treeview.Heading", background=COLORS["input"], foreground=COLORS["muted"],
                        relief="flat", borderwidth=0, padding=(10, 9), font=("Segoe UI", 9, "bold"))
        style.map("App.Treeview.Heading", background=[("active", COLORS["input"])])
        style.configure("App.Vertical.TScrollbar", background=COLORS["border"], troughcolor=COLORS["panel"],
                        borderwidth=0, arrowcolor=COLORS["muted"], lightcolor=COLORS["border"],
                        darkcolor=COLORS["border"], gripcount=0, width=10)
        style.map("App.Vertical.TScrollbar", background=[("active", COLORS["muted"])])
        # Native ttk checkbuttons retain keyboard/focus behavior with modern switch artwork.
        self._switch_images = [self._switch_image(False), self._switch_image(True), self._switch_image(False, disabled=True)]
        style.element_create("FreeLossless.Switch", "image", self._switch_images[0],
                             ("disabled", self._switch_images[2]), ("selected", self._switch_images[1]))
        style.layout("App.Switch.TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("FreeLossless.Switch", {"side": "right", "sticky": "e"}),
                ("Checkbutton.focus", {"side": "left", "sticky": "nswe", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"}),
                ]}),
            ]}),
        ])
        style.configure("App.Switch.TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"],
                        focuscolor=COLORS["accent"], padding=2, font=("Segoe UI", 10, "bold"))
        style.map("App.Switch.TCheckbutton", background=[("active", COLORS["panel"])])

    def _switch_image(self, enabled, disabled=False):
        width, height = round(38 * self._ui_scale), round(22 * self._ui_scale)
        image = tk.PhotoImage(master=self.root, width=width, height=height)
        track = COLORS["accent"] if enabled else COLORS["border"]
        knob = COLORS["muted"] if disabled else COLORS["text"]
        center_x = 27 if enabled else 11
        rows = []
        for y in range(height):
            pixels = []
            for x in range(width):
                logical_x, logical_y = x / self._ui_scale, y / self._ui_scale
                track_x = min(27, max(11, logical_x))
                inside_track = (logical_x - track_x) ** 2 + (logical_y - 11) ** 2 <= 100
                inside_knob = (logical_x - center_x) ** 2 + (logical_y - 11) ** 2 <= 49
                pixels.append(knob if inside_knob else track if inside_track else COLORS["panel"])
            rows.append("{" + " ".join(pixels) + "}")
        image.put(" ".join(rows))
        return image

    def _label(self, parent, text=None, *, muted=False, size=10, bold=False, **options):
        return tk.Label(parent, text=text, bg=parent.cget("bg"),
                        fg=COLORS["muted" if muted else "text"],
                        font=("Segoe UI", size, "bold" if bold else "normal"), **options)

    def _button(self, parent, text, command, primary=False, **options):
        return tk.Button(parent, text=text, command=command, cursor="hand2", relief=tk.FLAT,
                         bd=0, highlightthickness=1, highlightbackground=COLORS["border"],
                         highlightcolor=COLORS["accent"], padx=16, pady=9,
                         bg=COLORS["accent"] if primary else COLORS["input"],
                         fg=COLORS["background"] if primary else COLORS["text"],
                         activebackground=COLORS["accent_hover"] if primary else COLORS["border"],
                         activeforeground=COLORS["background"] if primary else COLORS["text"],
                         disabledforeground=COLORS["muted"],
                         font=("Segoe UI", 10, "bold" if primary else "normal"), **options)

    def _setup_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = tk.Frame(self.root, bg=COLORS["background"])
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 16))
        header.columnconfigure(1, weight=1)
        logo = tk.Canvas(header, width=44, height=44, bg=COLORS["background"], highlightthickness=0)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        draw_logo(logo, 0, 0, 44)
        self._label(header, _t("app.title"), size=22, bold=True).grid(row=0, column=1, sticky="w")
        self._label(header, _t("app.subtitle"), muted=True).grid(row=1, column=1, sticky="w")
        save_area = tk.Frame(header, bg=COLORS["background"])
        save_area.grid(row=0, column=2, rowspan=2, sticky="e", padx=(16, 0))
        self.save_dot = self._label(save_area, "●", size=10)
        self.save_dot.config(fg=COLORS["success"])
        self.save_dot.grid(row=0, column=0, padx=(0, 6))
        self._label(save_area, textvariable=self.save_status_var, size=9, wraplength=230,
                    justify=tk.RIGHT).grid(row=0, column=1, sticky="e")
        self._label(save_area, _t("save.in_this_device"), muted=True, size=9).grid(
            row=1, column=0, columnspan=2, sticky="e", pady=(4, 0))

        workspace = tk.Frame(self.root, bg=COLORS["background"])
        workspace.grid(row=1, column=0, sticky="nsew", padx=28)
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(0, weight=4, minsize=300)
        workspace.columnconfigure(1, weight=6, minsize=370)
        source_card = tk.Frame(workspace, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        source_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        source_card.columnconfigure(0, weight=1)
        source_card.rowconfigure(3, weight=1)
        self._setup_source_card(source_card)
        settings_card = tk.Frame(workspace, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        settings_card.grid(row=0, column=1, sticky="nsew")
        settings_card.columnconfigure(0, weight=1)
        settings_card.rowconfigure(1, weight=1)
        self._label(settings_card, _t("settings.section"), size=14, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=22, pady=(18, 10))
        self.settings_canvas = tk.Canvas(settings_card, bg=COLORS["panel"], highlightthickness=0,
                                         width=460, yscrollincrement=round(18 * self._ui_scale))
        self.settings_canvas.grid(row=1, column=0, sticky="nsew", padx=(22, 8), pady=(0, 16))
        scrollbar = ttk.Scrollbar(settings_card, orient=tk.VERTICAL, command=self.settings_canvas.yview,
                                  style="App.Vertical.TScrollbar")
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=(0, 16))
        self.settings_canvas.configure(yscrollcommand=scrollbar.set)
        self.settings_content = tk.Frame(self.settings_canvas, bg=COLORS["panel"])
        self.settings_content.columnconfigure(0, weight=1)
        content_id = self.settings_canvas.create_window((0, 0), window=self.settings_content, anchor="nw")
        self.settings_content.bind("<Configure>", lambda event: self.settings_canvas.configure(
            scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda event: self.settings_canvas.itemconfigure(content_id, width=event.width))
        self._setup_settings_card(self.settings_content)
        self._bind_settings_scroll(self.settings_canvas)

        footer = tk.Frame(self.root, bg=COLORS["background"])
        footer.grid(row=2, column=0, sticky="ew", padx=28, pady=(18, 22))
        footer.columnconfigure(0, weight=1)
        self._label(footer, textvariable=self.session_summary_var, bold=True).grid(row=0, column=0, sticky="w")
        self._label(footer, textvariable=self.shortcuts_hint_var, muted=True, size=9).grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        self._button(footer, _t("action.settings"), self._open_settings_dialog).grid(
            row=0, column=1, rowspan=2, padx=(12, 10))
        self._button(footer, _t("action.exit"), self._on_close).grid(row=0, column=2, rowspan=2, padx=(0, 10))
        self.start_button = self._button(footer, _t("action.start"), self._on_select, primary=True)
        self.start_button.grid(row=0, column=3, rowspan=2)

    def _setup_source_card(self, card):
        title = tk.Frame(card, bg=COLORS["panel"])
        title.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        self._label(title, _t("source.section"), size=14, bold=True).pack(anchor="w")
        self._label(title, _t("source.hint"), muted=True, size=9).pack(anchor="w", pady=(4, 0))
        segment = tk.Frame(card, bg=COLORS["input"])
        segment.grid(row=1, column=0, sticky="ew", padx=18)
        for column, (value, label) in enumerate((("window", _t("source.window")),
                                                 ("display", _t("source.monitor")))):
            segment.columnconfigure(column, weight=1)
            tk.Radiobutton(segment, text=label, value=value, variable=self.source_var, indicatoron=False,
                           command=self._refresh_list, relief=tk.FLAT, bd=0, highlightthickness=1,
                           highlightbackground=COLORS["input"], highlightcolor=COLORS["accent"],
                           selectcolor=COLORS["accent_dim"], bg=COLORS["input"], fg=COLORS["text"],
                           activebackground=COLORS["border"], activeforeground=COLORS["text"],
                           padx=12, pady=10, cursor="hand2").grid(row=0, column=column, sticky="ew")
        list_header = tk.Frame(card, bg=COLORS["panel"])
        list_header.grid(row=2, column=0, sticky="ew", padx=18, pady=(12, 8))
        list_header.columnconfigure(0, weight=1)
        self.list_label = self._label(list_header, size=9, bold=True)
        self.list_label.grid(row=0, column=0, sticky="w")
        self._label(list_header, textvariable=self.source_count_var, muted=True, size=9).grid(row=1, column=0, sticky="w")
        self._button(list_header, _t("source.refresh"), self._refresh_list).grid(
            row=0, column=1, rowspan=2, padx=(8, 0))
        list_frame = tk.Frame(card, bg=COLORS["panel"])
        list_frame.grid(row=3, column=0, sticky="nsew", padx=18)
        list_frame.columnconfigure(0, weight=1)
        # Keep enough of the list usable on short screens instead of collapsing it.
        list_frame.rowconfigure(0, weight=1, minsize=round(110 * self._ui_scale))
        self.tree = ttk.Treeview(list_frame, columns=("Title", "Process"), show="headings", selectmode="browse",
                                 height=4, style="App.Treeview")
        self.tree.heading("Title", text=_t("source.window_title"))
        self.tree.heading("Process", text=_t("source.process"))
        self.tree.column("Title", width=200, minwidth=100)
        self.tree.column("Process", width=120, minwidth=90)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview, style="App.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("alternate", background="#182334")
        self.tree.bind("<<TreeviewSelect>>", self._on_source_change)
        self.tree.bind("<Double-1>", self._on_select)
        self.tree.bind("<Return>", self._on_select)
        self.empty_label = tk.Label(list_frame, bg=COLORS["panel"], fg=COLORS["muted"],
                                    font=("Segoe UI", 10), justify=tk.CENTER,
                                    wraplength=240, padx=12, pady=12)
        summary = tk.Frame(card, bg=COLORS["input"])
        summary.grid(row=4, column=0, sticky="ew", padx=18, pady=(10, 14))
        selected_label = self._label(summary, textvariable=self.selected_title_var, bold=True, anchor="w")
        selected_label.pack(fill=tk.X, padx=12, pady=(8, 1))
        self.selected_detail_label = self._label(summary, textvariable=self.selected_detail_var, muted=True,
                                                 size=9, justify=tk.LEFT, anchor="w")
        self.selected_detail_label.pack(fill=tk.X, padx=12, pady=(0, 8))
        summary.bind("<Configure>", lambda event: (
            selected_label.config(wraplength=max(180, event.width - 24)),
            self.selected_detail_label.config(wraplength=max(180, event.width - 24))))

    def _section(self, parent, text, row):
        section = tk.Frame(parent, bg=COLORS["panel"])
        section.grid(row=row, column=0, sticky="ew", pady=(14 if row else 0, 0))
        section.columnconfigure(0, weight=1)
        self._label(section, text, muted=True, size=9, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 12))
        return section

    def _linked_combo(self, parent, source_var, labels, width=18):
        """Show translated labels while the setting keeps its canonical value."""
        display_var = tk.StringVar(self.root, value=labels.get(source_var.get(), source_var.get()))
        combo = self._combo(parent, display_var, (labels[value] for value in labels), width=width)
        reverse = {label: value for value, label in labels.items()}
        combo.bind("<<ComboboxSelected>>",
                   lambda event: source_var.set(reverse.get(display_var.get(), source_var.get())))
        self._choice_displays.append((source_var, display_var, labels))
        return combo

    def _sync_choice_displays(self):
        for source_var, display_var, labels in self._choice_displays:
            display_var.set(labels.get(source_var.get(), source_var.get()))

    def _combo(self, parent, variable, values, width=18):
        return ttk.Combobox(parent, textvariable=variable, values=tuple(values), state="readonly",
                            width=width, style="App.TCombobox", font=("Segoe UI", 10))

    def _slider(self, parent, variable, minimum, maximum, resolution=1):
        return tk.Scale(parent, from_=minimum, to=maximum, variable=variable, orient=tk.HORIZONTAL,
                        resolution=resolution, showvalue=False, highlightthickness=0, bd=0, relief=tk.FLAT,
                        bg=COLORS["panel"], fg=COLORS["text"], troughcolor=COLORS["input"],
                        activebackground=COLORS["accent_hover"], sliderrelief=tk.FLAT,
                        sliderlength=18, width=8, cursor="hand2")

    def _toggle_row(self, parent, row, title, detail, variable):
        line = tk.Frame(parent, bg=COLORS["panel"])
        line.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        line.columnconfigure(0, weight=1)
        switch = ttk.Checkbutton(line, text=title, variable=variable, style="App.Switch.TCheckbutton", cursor="hand2")
        switch.grid(row=0, column=0, sticky="ew")
        description = self._label(line, detail, muted=True, size=9, justify=tk.LEFT)
        description.grid(row=1, column=0, sticky="w", pady=(3, 0))
        line.bind("<Configure>", lambda event: description.config(wraplength=max(200, event.width - 60)))
        return switch

    def _setup_settings_card(self, parent):
        capture = self._section(parent, _t("section.capture_output"), 0)
        fields = tk.Frame(capture, bg=COLORS["panel"])
        fields.grid(row=1, column=0, sticky="ew")
        fields.columnconfigure((0, 1), weight=1, uniform="capture")
        self._label(fields, _t("field.capture_backend"), size=9).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._label(fields, _t("field.output_scale"), size=9).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 6))
        self.mode_combo = self._linked_combo(
            fields, self.mode_var, {value: _t(MODE_LABEL_KEYS[value]) for value in CAPTURE_MODES})
        self.mode_combo.grid(row=1, column=0, sticky="ew")
        scale_labels = {value: (value if value != "Fullscreen" else _t("scale.fullscreen"))
                        for value in SCALE_OPTIONS}
        self.scale_combo = self._linked_combo(fields, self.scale_var, scale_labels)
        self.scale_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        fps_line = tk.Frame(capture, bg=COLORS["panel"])
        fps_line.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        fps_line.columnconfigure(0, weight=1)
        self._label(fps_line, _t("field.output_fps"), bold=True).grid(row=0, column=0, sticky="w")
        self._label(fps_line, textvariable=self.fps_value_var, bold=True).grid(row=0, column=1, sticky="e")
        self.fps_scale = self._slider(capture, self.fps_var, 30, 120)
        self.fps_scale.grid(row=3, column=0, sticky="ew", pady=(6, 3))
        presets = tk.Frame(capture, bg=COLORS["panel"])
        presets.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.fps_presets = {}
        for column, value in enumerate((30, 60, 90, 120)):
            presets.columnconfigure(column, weight=1)
            button = self._button(presets, f"{value} FPS", lambda fps=value: self.fps_var.set(fps))
            button.config(padx=4, pady=5, font=("Segoe UI", 9))
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
            self.fps_presets[value] = button

        image = self._section(parent, _t("section.image_quality"), 1)
        self._label(image, _t("field.algorithm"), size=9).grid(row=1, column=0, sticky="w", pady=(0, 6))
        algo_labels = {value: _t(ALGORITHM_LABEL_KEYS[value]) for value in ALGORITHM_OPTIONS}
        self.algo_combo = self._linked_combo(image, self.algo_var, algo_labels)
        self.algo_combo.grid(row=2, column=0, sticky="ew")
        self.algo_hint_var = tk.StringVar(self.root)
        self.algo_hint_label = self._label(image, textvariable=self.algo_hint_var, muted=True,
                                           size=9, justify=tk.LEFT)
        self.algo_hint_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.filters_check = self._toggle_row(image, 4, _t("toggle.filters"),
                                              _t("toggle.filters_hint"), self.filters_var)
        self.filters_hint_var = tk.StringVar(self.root)
        self.filters_hint_label = self._label(image, textvariable=self.filters_hint_var, muted=True,
                                               size=9, justify=tk.LEFT)
        self.filters_hint_label.grid(row=5, column=0, sticky="w", pady=(0, 4))
        sharp_line = tk.Frame(image, bg=COLORS["panel"])
        sharp_line.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        sharp_line.columnconfigure(0, weight=1)
        self._label(sharp_line, _t("field.sharpness"), bold=True).grid(row=0, column=0, sticky="w")
        self._label(sharp_line, textvariable=self.sharp_value_var, bold=True).grid(row=0, column=1, sticky="e")
        self.sharp_scale = self._slider(image, self.sharp_var, 0, 100)
        self.sharp_scale.grid(row=7, column=0, sticky="ew", pady=(6, 8))

        reshade_section = self._section(parent, _t("section.reshade"), 2)
        self._label(reshade_section, _t("field.display_mode"), size=9).grid(row=1, column=0, sticky="w",
                                                                           pady=(0, 6))
        mode_labels = {value: _t(DISPLAY_MODE_LABEL_KEYS[value]) for value in DISPLAY_MODES}
        self.display_mode_combo = self._linked_combo(reshade_section, self.display_mode_var, mode_labels)
        self.display_mode_combo.grid(row=2, column=0, sticky="ew")
        self._label(reshade_section, _t("display.hint"), muted=True, size=9,
                    justify=tk.LEFT).grid(row=3, column=0, sticky="w", pady=(4, 8))
        self.reshade_status_var = tk.StringVar(self.root)
        self.reshade_status_label = self._label(reshade_section, textvariable=self.reshade_status_var,
                                                muted=True, size=9, justify=tk.LEFT)
        self.reshade_status_label.grid(row=4, column=0, sticky="w")
        self.reshade_button = self._button(reshade_section, _t("reshade.download"),
                                           self._download_reshade)
        self.reshade_button.grid(row=5, column=0, sticky="w", pady=(8, 0))

        filters = self._section(parent, _t("section.filters"), 3)
        self._label(filters, _t("field.filter_preset"), size=9).grid(row=1, column=0, sticky="w",
                                                                     pady=(0, 6))
        filter_labels = {value: _t(FILTER_LABEL_KEYS[value]) for value in FILTER_PRESETS}
        self.filter_combo = self._linked_combo(filters, self.filter_var, filter_labels)
        self.filter_combo.grid(row=2, column=0, sticky="ew")
        self.filter_hint_var = tk.StringVar(self.root)
        self._label(filters, textvariable=self.filter_hint_var, muted=True, size=9,
                    justify=tk.LEFT).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.reshade_hint_var = tk.StringVar(self.root)
        self.reshade_hint_label = self._label(filters, textvariable=self.reshade_hint_var,
                                              muted=True, size=9, justify=tk.LEFT)
        self.reshade_hint_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

        generation = self._section(parent, _t("section.frame_generation"), 4)
        self.fg_check = self._toggle_row(generation, 1, _t("toggle.interpolation"),
                                        _t("toggle.interpolation_hint"), self.fg_var)
        engine_labels = {value: _t(ENGINE_LABEL_KEYS[value]) for value in ENGINE_OPTIONS}
        self.engine_combo = self._linked_combo(generation, self.engine_var, engine_labels)
        self.engine_combo.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        multiplier_line = tk.Frame(generation, bg=COLORS["panel"])
        multiplier_line.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        multiplier_line.columnconfigure(0, weight=1)
        self._label(multiplier_line, _t("field.frame_generation"), bold=True).grid(row=0, column=0, sticky="w")
        self._label(multiplier_line, textvariable=self.multiplier_value_var, bold=True).grid(
            row=0, column=1, sticky="e")
        self.multiplier_scale = self._slider(generation, self.multiplier_var, MULTIPLIER_MIN,
                                             MULTIPLIER_MAX, resolution=MULTIPLIER_STEP)
        self.multiplier_scale.grid(row=4, column=0, sticky="ew", pady=(6, 3))
        self.multiplier_hint_label = self._label(generation, textvariable=self.multiplier_hint_var,
                                                 muted=True, size=9, justify=tk.LEFT)
        self.multiplier_hint_label.grid(row=5, column=0, sticky="w", pady=(0, 8))
        generation.bind("<Configure>", lambda event: self.multiplier_hint_label.config(
            wraplength=max(200, event.width - 24)))
        advanced = self._section(parent, _t("section.advanced"), 5)
        self.ultra_smooth_check = self._toggle_row(advanced, 1, _t("toggle.ultra_smooth"),
                                                   _t("toggle.ultra_smooth_hint"), self.ultra_smooth_var)
        self.perf_mode_check = self._toggle_row(advanced, 2, _t("toggle.performance"),
                                                _t("toggle.performance_hint"), self.perf_mode_var)
        self.low_latency_check = self._toggle_row(advanced, 3, _t("toggle.low_latency"),
                                                  _t("toggle.low_latency_hint"), self.low_latency_var)

    def _open_settings_dialog(self):
        """Modal dialog for the global hotkeys and overlay preferences."""
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            self._settings_dialog.focus_force()
            return
        dialog = tk.Toplevel(self.root)
        self._settings_dialog = dialog
        dialog.title(_t("dialog.title"))
        dialog.configure(bg=COLORS["panel"])
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)

        body = tk.Frame(dialog, bg=COLORS["panel"])
        body.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 8))
        body.columnconfigure(0, weight=1)
        self._label(body, _t("dialog.title"), size=16, bold=True).grid(row=0, column=0, sticky="w")
        self._label(body, _t("dialog.subtitle"), muted=True, size=9).grid(
            row=1, column=0, sticky="w", pady=(4, 0))

        hotkeys = self._section(body, _t("dialog.hotkeys"), 2)
        fields = tk.Frame(hotkeys, bg=COLORS["panel"])
        fields.grid(row=1, column=0, sticky="ew")
        fields.columnconfigure(1, weight=1)
        dialog_vars = {}
        for row, key in enumerate(HOTKEY_SETTING_KEYS):
            variable = tk.StringVar(dialog, value=getattr(self, f"{key}_var").get())
            dialog_vars[key] = variable
            self._label(fields, _t(f"hotkey.{key.removeprefix('hotkey_')}"), size=9).grid(
                row=row, column=0, sticky="w", pady=(0, 8), padx=(0, 14))
            combo = self._combo(fields, variable, HOTKEY_OPTIONS, width=6)
            combo.grid(row=row, column=1, sticky="e", pady=(0, 8))
            combo.bind("<<ComboboxSelected>>", lambda event: self._validate_dialog_hotkeys(dialog_vars))
        self.dialog_error_var = tk.StringVar(dialog)
        self.dialog_error_label = self._label(hotkeys, textvariable=self.dialog_error_var,
                                              muted=True, size=9, justify=tk.LEFT)
        self.dialog_error_label.grid(row=2, column=0, sticky="w", pady=(0, 6))
        hotkeys.bind("<Configure>", lambda event: self.dialog_error_label.config(
            wraplength=max(220, event.width - 24)))

        overlay = self._section(body, _t("dialog.overlay"), 3)
        show_fps = tk.BooleanVar(dialog, value=bool(self.show_fps_var.get()))
        dialog_vars["show_fps"] = show_fps
        self._toggle_row(overlay, 1, _t("toggle.show_fps"), _t("toggle.show_fps_hint"), show_fps)

        preferences = self._section(body, _t("dialog.preferences"), 4)
        language_line = tk.Frame(preferences, bg=COLORS["panel"])
        language_line.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        language_line.columnconfigure(1, weight=1)
        self._label(language_line, _t("dialog.language"), size=9).grid(row=0, column=0, sticky="w",
                                                                      padx=(0, 14))
        language = tk.StringVar(dialog, value=i18n.language_name(self.language_var.get()))
        dialog_vars["language"] = language
        self.language_combo = self._combo(language_line, language, i18n.LANGUAGE_NAMES.values(), width=22)
        self.language_combo.grid(row=0, column=1, sticky="e")
        self._label(preferences, _t("dialog.language_hint"), muted=True, size=9).grid(
            row=2, column=0, sticky="w", pady=(0, 12))
        self._label(preferences, _t("dialog.preferences_file"), muted=True, size=9).grid(
            row=3, column=0, sticky="w")
        self._label(preferences, str(self.settings_store.path), muted=True, size=9,
                    justify=tk.LEFT).grid(row=4, column=0, sticky="w", pady=(2, 10))
        actions = tk.Frame(preferences, bg=COLORS["panel"])
        actions.grid(row=5, column=0, sticky="w")
        self._button(actions, _t("action.open_folder"), self._open_settings_folder).grid(row=0, column=0)
        self._button(actions, _t("action.reset"), lambda: self._reset_dialog(dialog_vars)).grid(
            row=0, column=1, padx=(8, 0))

        buttons = tk.Frame(dialog, bg=COLORS["panel"])
        buttons.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 22))
        buttons.columnconfigure(0, weight=1)
        self._label(buttons, _t("dialog.hint_keys"), muted=True, size=9).grid(row=0, column=0, sticky="w")
        self._button(buttons, _t("action.cancel"), self._close_settings_dialog).grid(row=0, column=1, padx=(8, 8))
        self._button(buttons, _t("action.save"), lambda: self._apply_dialog_settings(dialog_vars),
                     primary=True).grid(row=0, column=2)

        dialog.protocol("WM_DELETE_WINDOW", self._close_settings_dialog)
        dialog.bind("<Escape>", lambda event: self._close_settings_dialog())
        dialog.bind("<Return>", lambda event: self._apply_dialog_settings(dialog_vars))
        self._center_dialog(dialog)
        dialog.grab_set()
        dialog.focus_force()

    def _center_dialog(self, dialog):
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 3)
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _validate_dialog_hotkeys(self, dialog_vars):
        """Returns True when every action owns a different key."""
        hotkeys = {key: variable.get() for key, variable in dialog_vars.items()
                   if key in HOTKEY_SETTING_KEYS}
        conflicts = hotkey_conflicts(hotkeys)
        if conflicts:
            self.dialog_error_var.set(_t("dialog.error_conflict"))
            self.dialog_error_label.config(fg=COLORS["warning"])
            return False
        self.dialog_error_var.set(_t("dialog.error_ok"))
        self.dialog_error_label.config(fg=COLORS["success"])
        return True

    def _reset_dialog(self, dialog_vars):
        for key in HOTKEY_SETTING_KEYS:
            dialog_vars[key].set(DEFAULT_SETTINGS[key])
        dialog_vars["show_fps"].set(DEFAULT_SETTINGS["show_fps"])
        dialog_vars["language"].set(i18n.language_name(DEFAULT_SETTINGS["language"]))
        self._validate_dialog_hotkeys(dialog_vars)

    def _open_settings_folder(self):
        folder = self.settings_store.path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(folder)  # noqa: S606 - opens the user's own settings folder
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showinfo(_t("action.open_folder"), f"{folder}\n\n{exc}", parent=self.root)

    def _close_settings_dialog(self):
        if self._settings_dialog is not None:
            dialog, self._settings_dialog = self._settings_dialog, None
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

    def _apply_dialog_settings(self, dialog_vars):
        if not self._validate_dialog_hotkeys(dialog_vars):
            messagebox.showwarning(_t("dialog.conflict_title"),
                                   _t("dialog.conflict_body"), parent=self._settings_dialog)
            return
        for key in HOTKEY_SETTING_KEYS:
            getattr(self, f"{key}_var").set(dialog_vars[key].get())
        self.show_fps_var.set(bool(dialog_vars["show_fps"].get()))
        language = i18n.language_code(dialog_vars["language"].get())
        language_changed = i18n.normalize_language(self.language_var.get()) != language
        self.language_var.set(language)
        self._close_settings_dialog()
        self._save_settings(notify=True)
        if language_changed:
            self._apply_language(language)

    def _apply_language(self, language):
        """Rebuild the window in the new language without losing any preference."""
        self._loading_settings = True
        try:
            self.language_var.set(i18n.set_language(language))
            for child in self.root.winfo_children():
                child.destroy()
            self._choice_displays = []
            self._setup_ui()
            self._refresh_list()
            self._update_setting_display()
            self._set_save_status(_t("save.saved"), COLORS["success"])
        finally:
            self._loading_settings = False

    def _bind_settings_scroll(self, widget):
        widget.bind("<MouseWheel>", self._scroll_settings, add="+")
        widget.bind("<Button-4>", self._scroll_settings, add="+")
        widget.bind("<Button-5>", self._scroll_settings, add="+")
        widget.bind("<FocusIn>", self._reveal_setting, add="+")
        for child in widget.winfo_children():
            self._bind_settings_scroll(child)

    def _reveal_setting(self, event):
        # Tab navigation must not leave keyboard users focused on off-screen controls.
        if self._closing:
            return
        content_height = self.settings_content.winfo_height()
        viewport_height = self.settings_canvas.winfo_height()
        if content_height <= viewport_height:
            return
        top = event.widget.winfo_rooty() - self.settings_content.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        visible_top = self.settings_canvas.canvasy(0)
        margin = round(24 * self._ui_scale)
        if top < visible_top:
            self.settings_canvas.yview_moveto(max(0, top - margin) / content_height)
        elif bottom > visible_top + viewport_height:
            self.settings_canvas.yview_moveto((bottom - viewport_height + margin) / content_height)

    def _scroll_settings(self, event):
        if self.settings_content.winfo_height() <= self.settings_canvas.winfo_height():
            return "break"
        if getattr(event, "num", None) in (4, 5):
            units = -1 if event.num == 4 else 1
        else:
            units = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.settings_canvas.yview_scroll(units * 3, "units")
        return "break"

    def _remember_selected_source(self):
        selected = self.tree.selection()
        source = self.sources.get(selected[0]) if selected else None
        if source:
            identity = source_identity(source)
            if identity:
                self.preferred_sources[source.get("source_type", "window")] = identity
        return source

    def _find_remembered_source(self):
        kind = self.source_var.get()
        preferred = self.preferred_sources.get(kind)
        if not preferred:
            return None
        exact = [iid for iid, source in self.sources.items() if source_identity(source) == preferred]
        if len(exact) == 1:
            return exact[0]
        if kind == "window":
            # Titles can change between launches; only fall back when the process is unique.
            matches = [iid for iid, source in self.sources.items()
                       if source.get("process", "").casefold() == preferred["process"].casefold()]
            if len(matches) == 1:
                return matches[0]
        return None

    def _refresh_list(self):
        self._remember_selected_source()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.sources = {}
        is_display = self.source_var.get() == "display"
        self.list_label.config(text=_t("source.monitors_detected") if is_display
                               else _t("source.windows_detected"))
        self.tree.heading("Title", text=_t("source.monitor") if is_display else _t("source.window_title"))
        self.tree.heading("Process", text=_t("source.resolution_position") if is_display
                          else _t("source.process"))
        sources = DisplaySelector.get_displays() if is_display else self.selector.get_visible_windows()
        for index, source in enumerate(sources):
            source = dict(source)
            source.setdefault("source_type", "window")
            if is_display:
                left, top, right, bottom = source["rect"]
                detail = f"{right - left} x {bottom - top} ({left}, {top})"
            else:
                detail = source["process"]
            iid = str(index)
            self.sources[iid] = source
            self.tree.insert("", tk.END, values=(source["title"], detail), iid=iid,
                             tags=("alternate",) if index % 2 else ())
        count = len(self.sources)
        self.source_count_var.set(_t("source.count_one") if count == 1
                                  else _t("source.count_many", count=count))
        if self.sources:
            self.empty_label.place_forget()
        else:
            self.empty_label.config(text=_t("source.empty_monitors") if is_display
                                    else _t("source.empty_windows"))
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        remembered = self._find_remembered_source()
        if remembered is not None:
            self.tree.selection_set(remembered)
            self.tree.focus(remembered)
            self.tree.see(remembered)
        self._update_source_display()

    def _update_source_display(self):
        selected = self.tree.selection()
        source = self.sources.get(selected[0]) if selected else None
        self.start_button.config(state=tk.NORMAL if source else tk.DISABLED,
                                 bg=COLORS["accent"] if source else COLORS["input"])
        if not source:
            self.selected_title_var.set(_t("source.none_selected"))
            self.selected_detail_var.set(_t("source.select_hint"))
        else:
            title = source["title"]
            self.selected_title_var.set(title if len(title) <= 72 else title[:69] + "…")
            detail = source.get("process")
            if source.get("source_type") == "display":
                left, top, right, bottom = source["rect"]
                detail = f"{right - left} × {bottom - top}  ·  {_t('source.full_monitor')}"
            self.selected_detail_var.set(detail)

    def _refresh_reshade_hint(self):
        """Tell the user when the selected game already runs ReShade.

        Nothing is installed or injected into the game: the overlay captures the game's
        final image, so whatever ReShade does in there already reaches this preview.
        Knowing it avoids trying to stack the same look twice.
        """
        source = self.selected_source or {}
        process = source.get("process") if source.get("source_type") == "window" else None
        if not process:
            self.reshade_hint_var.set("")
            return
        try:
            _directory, files = reshade.installed_for_process(process)
        except Exception:
            files = []
        if files:
            self.reshade_hint_var.set(_t("filter.reshade_found", files=", ".join(sorted(files)[:3])))
            self.reshade_hint_label.config(fg=COLORS["success"])
        else:
            self.reshade_hint_var.set("")

    def _refresh_reshade_status(self):
        """Show whether this app folder already has ReShade installed."""
        try:
            found = reshade.detect()
        except Exception:
            found = []
        if found:
            self.reshade_status_var.set(_t("reshade.found", files=", ".join(found[:3])))
            self.reshade_status_label.config(fg=COLORS["success"])
        else:
            self.reshade_status_var.set(_t("reshade.missing"))
            self.reshade_status_label.config(fg=COLORS["muted"])

    def _download_reshade(self):
        """Fetch ReShade's own installer next to the app, in the background.

        ReShade is installed by its installer, not by us: the download only saves the
        file and shows where it is, because the DLL must be placed by the user in the
        folder of the program that will be hooked.
        """
        self.reshade_button.config(state=tk.DISABLED)
        self.reshade_status_var.set(_t("reshade.downloading"))
        self.reshade_status_label.config(fg=COLORS["accent"])
        self._reshade_result = None
        threading.Thread(target=self._fetch_reshade, daemon=True).start()
        # Tk is not thread-safe: the download happens in a thread, and the menu polls
        # for the result from its own thread.
        self.root.after(RESHADE_POLL_MS, self._poll_reshade_download)

    def _fetch_reshade(self):
        """Runs in the download thread; never touches the interface."""
        try:
            self._reshade_result = reshade.download_installer()
        except Exception as exc:
            self._reshade_result = (None, str(exc))

    def _poll_reshade_download(self):
        """Runs in the interface thread until the download result shows up."""
        result = getattr(self, "_reshade_result", None)
        if result is None:
            if not self._closing:
                self.root.after(RESHADE_POLL_MS, self._poll_reshade_download)
            return
        self._reshade_result = None
        self._reshade_download_finished(*result)

    def _reshade_download_finished(self, path, error):
        self.reshade_button.config(state=tk.NORMAL)
        if error:
            self.reshade_status_var.set(_t("reshade.failed", error=error))
            self.reshade_status_label.config(fg=COLORS["warning"])
            return
        exe = "FreeLossless.exe" if getattr(sys, "frozen", False) else "FreeLossless.exe (build)"
        self.reshade_status_var.set(_t("reshade.downloaded", path=str(path), exe=exe))
        self.reshade_status_label.config(fg=COLORS["success"])
        reshade.open_folder(path)

    def _update_setting_display(self):
        fps = self.fps_var.get()
        multiplier = self.multiplier_var.get()
        generation_on = bool(self.fg_var.get())
        self.fps_value_var.set(f"{fps} FPS")
        self.sharp_value_var.set(f"{self.sharp_var.get()}%")
        self.multiplier_value_var.set(_t("multiply.value", multiplier=multiplier))
        for value, button in self.fps_presets.items():
            button.config(bg=COLORS["accent_dim"] if fps == value else COLORS["input"])
        self.engine_combo.configure(state="readonly" if generation_on else "disabled")
        self.multiplier_scale.configure(state=tk.NORMAL if generation_on else tk.DISABLED)
        self._sync_choice_displays()
        filters_on = bool(self.filters_var.get())
        self.algo_combo.configure(state="readonly" if filters_on else "disabled")
        self.sharp_scale.configure(state=tk.NORMAL if filters_on else tk.DISABLED)
        self.filters_hint_var.set("" if filters_on else _t("filters.disabled"))
        self.filters_hint_label.config(fg=COLORS["warning"])
        self.filter_combo.configure(state="readonly" if filters_on else "disabled")
        self.algo_hint_var.set(_t(ALGORITHM_HINT_KEYS.get(self.algo_var.get(), "algo.hint.bicubic")))
        self.filter_hint_var.set(_t("filter.hint"))
        if not generation_on:
            hint = _t("multiply.disabled")
            tone = "muted"
        else:
            fields = {"extra": multiplier - 1, "capture": max(1, round(fps / multiplier)), "fps": fps}
            hint = _t("multiply.warning" if multiplier >= 8 else "multiply.hint", **fields)
            tone = "warning" if multiplier >= 8 else "muted"
        self.multiplier_hint_var.set(hint)
        self.multiplier_hint_label.config(fg=COLORS[tone])
        self.shortcuts_hint_var.set(_t("footer.shortcuts", stop=self.hotkey_stop_var.get(),
                                       fps=self.hotkey_fps_var.get(), fsr=self.hotkey_fsr_var.get()))
        scale = (_t("footer.fullscreen") if self.scale_var.get() == "Fullscreen"
                 else f"{self.scale_var.get()}×")
        self.session_summary_var.set(_t("footer.summary" if generation_on else "footer.summary_off",
                                        fps=fps, scale=scale, multiplier=multiplier))

    def _on_settings_change(self, *args):
        if self._loading_settings or self._closing:
            return
        self._update_setting_display()
        self._schedule_save()

    def _on_source_change(self, event=None):
        if self._closing:
            return
        self._remember_selected_source()
        self._update_source_display()
        self._refresh_reshade_hint()
        self._schedule_save()

    def _collect_settings(self):
        data = {key: getattr(self, name).get() for key, name in self.SETTING_VARIABLES.items()}
        return normalize_settings({**data, "preferred_sources": self.preferred_sources})

    def _set_save_status(self, text, color):
        self.save_status_var.set(text)
        self.save_dot.config(fg=color)

    def _cancel_pending_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._save_job = None

    def _schedule_save(self):
        if self._loading_settings or self._closing:
            return
        self._cancel_pending_save()
        if self._collect_settings() == self._last_saved_settings:
            self._set_save_status(_t("save.nothing"), COLORS["success"])
            return
        self._set_save_status(_t("save.saving"), COLORS["accent"])
        self._save_job = self.root.after(self.SAVE_DELAY_MS, self._autosave)

    def _autosave(self):
        self._save_job = None
        self._save_settings()

    def _save_settings(self, notify=False):
        self._cancel_pending_save()
        settings = self._collect_settings()
        try:
            self.settings_store.save(settings)
        except OSError as exc:
            self._set_save_status(_t("save.failed"), COLORS["warning"])
            if notify:
                messagebox.showwarning(
                    _t("save.error_title"),
                    _t("save.error_body", path=self.settings_store.path, error=exc),
                    parent=self.root,
                )
            return False
        self._last_saved_settings = settings
        self._set_save_status(_t("save.saved"), COLORS["success"])
        return True

    def _close_root(self):
        self._cancel_pending_save()
        self._closing = True
        self.root.destroy()

    def _on_close(self, event=None):
        if self._closing:
            return
        self._close_settings_dialog()
        self._remember_selected_source()
        self._save_settings(notify=True)
        self._close_root()

    def _on_select(self, event=None):
        if self._closing:
            return "break"
        source = self._remember_selected_source()
        if not source:
            messagebox.showinfo(_t("msg.select_source_title"), _t("msg.select_source_body"),
                                parent=self.root)
            return "break"
        settings = self._collect_settings()
        self.selected_source = {**source, **{key: value for key, value in settings.items()
                                          if key not in ("version", "preferred_sources", "source_type")}}
        self.selected_source["language"] = i18n.get_language()
        # Flush the debounce before destroying Tk or initializing overlay/GPU resources.
        self._save_settings(notify=True)
        self._close_root()
        return "break"

    def get_selection(self):
        self.root.mainloop()
        return self.selected_source


if __name__ == "__main__":
    ui = GameSelectorUI()  # noqa: F841 - manual smoke run
    selection = ui.get_selection()
    print(f"User selected: {selection}")
