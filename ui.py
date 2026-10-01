import tkinter as tk
from tkinter import ttk, messagebox

from selector import WindowSelector, DisplaySelector
from settings import (
    ALGORITHM_OPTIONS, CAPTURE_MODES, ENGINE_OPTIONS, SCALE_OPTIONS,
    SettingsStore, normalize_settings, source_identity,
)


COLORS = {
    "background": "#0C111B",
    "panel": "#141D2B",
    "input": "#1D293B",
    "border": "#2A3950",
    "text": "#F1F5FC",
    "muted": "#9CAEC7",
    "accent": "#7695FF",
    "accent_hover": "#92AAFF",
    "accent_dim": "#293D6B",
    "success": "#69DDB2",
    "warning": "#F0BC78",
}


class GameSelectorUI:
    SAVE_DELAY_MS = 500
    SETTING_VARIABLES = {
        "source_type": "source_var", "mode": "mode_var", "fps": "fps_var",
        "scale": "scale_var", "algo": "algo_var", "sharpness": "sharp_var",
        "fg_enabled": "fg_var", "engine_type": "engine_var",
        "ultra_smooth": "ultra_smooth_var", "performance_mode": "perf_mode_var",
        "low_latency": "low_latency_var",
    }

    def __init__(self, settings_store=None):
        self.settings_store = settings_store if settings_store is not None else SettingsStore()
        settings = self.settings_store.load()
        self.preferred_sources = settings["preferred_sources"]
        self._last_saved_settings = normalize_settings(settings) if not self.settings_store.load_error else None
        self._save_job = None
        self._loading_settings = True
        self._closing = False
        self.selected_source = None
        self.sources = {}
        self.selector = WindowSelector()
        self.root = tk.Tk()
        self.root.title("Free Lossless — Controle de overlay")
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
        self.save_status_var = tk.StringVar(self.root, value="Salvamento automático ativo")
        self.source_count_var = tk.StringVar(self.root)
        self.selected_title_var = tk.StringVar(self.root)
        self.selected_detail_var = tk.StringVar(self.root)
        self.session_summary_var = tk.StringVar(self.root)
        self.fps_value_var = tk.StringVar(self.root)
        self.sharp_value_var = tk.StringVar(self.root)

        self._setup_style()
        self._setup_ui()
        self._refresh_list()
        self._update_setting_display()
        for name in self.SETTING_VARIABLES.values():
            getattr(self, name).trace_add("write", self._on_settings_change)
        self._loading_settings = False
        if self.settings_store.load_error:
            self._set_save_status("Preferências indisponíveis; usando padrão", COLORS["warning"])
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
        except (AttributeError, OSError, tk.TclError):
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
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 20))
        header.columnconfigure(1, weight=1)
        logo = tk.Canvas(header, width=44, height=44, bg=COLORS["background"], highlightthickness=0)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        logo.create_rectangle(4, 4, 30, 30, outline=COLORS["accent"], width=2)
        logo.create_rectangle(14, 14, 40, 40, fill=COLORS["background"], outline=COLORS["success"], width=2)
        logo.create_line(20, 28, 25, 23, 30, 28, 35, 23, fill=COLORS["success"], width=2)
        self._label(header, "Free Lossless", size=22, bold=True).grid(row=0, column=1, sticky="w")
        self._label(header, "Mais fluidez. Sem modificar seu jogo.", muted=True).grid(row=1, column=1, sticky="w")
        save_area = tk.Frame(header, bg=COLORS["background"])
        save_area.grid(row=0, column=2, rowspan=2, sticky="e", padx=(16, 0))
        self.save_dot = self._label(save_area, "●", size=10)
        self.save_dot.config(fg=COLORS["success"])
        self.save_dot.grid(row=0, column=0, padx=(0, 6))
        self._label(save_area, textvariable=self.save_status_var, size=9, wraplength=230,
                    justify=tk.RIGHT).grid(row=0, column=1, sticky="e")
        self._label(save_area, "Preferências salvas neste dispositivo", muted=True, size=9).grid(
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
        self._label(settings_card, "02  /  Ajustes do overlay", size=14, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=22, pady=(20, 12))
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
        self._label(footer, "F11 retorna ao menu  ·  Ctrl + Enter inicia o overlay", muted=True, size=9).grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        self._button(footer, "Sair", self._on_close).grid(row=0, column=1, rowspan=2, padx=(12, 10))
        self.start_button = self._button(footer, "Iniciar overlay  →", self._on_select, primary=True)
        self.start_button.grid(row=0, column=2, rowspan=2)

    def _setup_source_card(self, card):
        title = tk.Frame(card, bg=COLORS["panel"])
        title.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 16))
        self._label(title, "01  /  Fonte de captura", size=14, bold=True).pack(anchor="w")
        self._label(title, "Escolha uma janela ou um monitor.", muted=True, size=9).pack(anchor="w", pady=(5, 0))
        segment = tk.Frame(card, bg=COLORS["input"])
        segment.grid(row=1, column=0, sticky="ew", padx=20)
        for column, (value, label) in enumerate((("window", "Janela / jogo"), ("display", "Monitor"))):
            segment.columnconfigure(column, weight=1)
            tk.Radiobutton(segment, text=label, value=value, variable=self.source_var, indicatoron=False,
                           command=self._refresh_list, relief=tk.FLAT, bd=0, highlightthickness=1,
                           highlightbackground=COLORS["input"], highlightcolor=COLORS["accent"],
                           selectcolor=COLORS["accent_dim"], bg=COLORS["input"], fg=COLORS["text"],
                           activebackground=COLORS["border"], activeforeground=COLORS["text"],
                           padx=12, pady=10, cursor="hand2").grid(row=0, column=column, sticky="ew")
        list_header = tk.Frame(card, bg=COLORS["panel"])
        list_header.grid(row=2, column=0, sticky="ew", padx=20, pady=(16, 10))
        list_header.columnconfigure(0, weight=1)
        self.list_label = self._label(list_header, size=9, bold=True)
        self.list_label.grid(row=0, column=0, sticky="w")
        self._label(list_header, textvariable=self.source_count_var, muted=True, size=9).grid(row=1, column=0, sticky="w")
        self._button(list_header, "↻ Atualizar", self._refresh_list).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        list_frame = tk.Frame(card, bg=COLORS["panel"])
        list_frame.grid(row=3, column=0, sticky="nsew", padx=20)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_frame, columns=("Title", "Process"), show="headings", selectmode="browse",
                                 height=5, style="App.Treeview")
        self.tree.heading("Title", text="Título da janela")
        self.tree.heading("Process", text="Processo")
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
        summary.grid(row=4, column=0, sticky="ew", padx=20, pady=(12, 16))
        self._label(summary, "FONTE SELECIONADA", muted=True, size=8, bold=True).pack(anchor="w", padx=12, pady=(10, 4))
        selected_label = self._label(summary, textvariable=self.selected_title_var, bold=True, anchor="w")
        selected_label.pack(fill=tk.X, padx=12)
        detail_label = self._label(summary, textvariable=self.selected_detail_var, muted=True, size=9,
                                   justify=tk.LEFT, anchor="w")
        detail_label.pack(fill=tk.X, padx=12, pady=(4, 10))
        summary.bind("<Configure>", lambda event: (
            selected_label.config(wraplength=max(180, event.width - 24)),
            detail_label.config(wraplength=max(180, event.width - 24))))
        shortcuts = tk.Frame(card, bg=COLORS["panel"])
        shortcuts.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 18))
        self._label(shortcuts, "ATALHOS DO OVERLAY", muted=True, size=8, bold=True).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 7))
        for column, (key, description) in enumerate((("F9", "FSR"), ("F10", "FPS"), ("F11", "Menu"))):
            shortcuts.columnconfigure(column, weight=1)
            group = tk.Frame(shortcuts, bg=COLORS["input"])
            group.grid(row=1, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
            self._label(group, key, size=9, bold=True).pack(side=tk.LEFT, padx=(8, 4), pady=6)
            self._label(group, description, muted=True, size=9).pack(side=tk.LEFT, padx=(0, 8))

    def _section(self, parent, text, row):
        section = tk.Frame(parent, bg=COLORS["panel"])
        section.grid(row=row, column=0, sticky="ew", pady=(14 if row else 0, 0))
        section.columnconfigure(0, weight=1)
        self._label(section, text, muted=True, size=9, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 12))
        return section

    def _combo(self, parent, variable, values, width=18):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width,
                            style="App.TCombobox", font=("Segoe UI", 10))

    def _slider(self, parent, variable, minimum, maximum):
        return tk.Scale(parent, from_=minimum, to=maximum, variable=variable, orient=tk.HORIZONTAL,
                        resolution=1, showvalue=False, highlightthickness=0, bd=0, relief=tk.FLAT,
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
        capture = self._section(parent, "CAPTURA E SAÍDA", 0)
        fields = tk.Frame(capture, bg=COLORS["panel"])
        fields.grid(row=1, column=0, sticky="ew")
        fields.columnconfigure((0, 1), weight=1, uniform="capture")
        self._label(fields, "Backend de captura", size=9).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._label(fields, "Escala de saída", size=9).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 6))
        self.mode_combo = self._combo(fields, self.mode_var, CAPTURE_MODES)
        self.mode_combo.grid(row=1, column=0, sticky="ew")
        self.scale_combo = self._combo(fields, self.scale_var, SCALE_OPTIONS)
        self.scale_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        fps_line = tk.Frame(capture, bg=COLORS["panel"])
        fps_line.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        fps_line.columnconfigure(0, weight=1)
        self._label(fps_line, "FPS de saída", bold=True).grid(row=0, column=0, sticky="w")
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

        image = self._section(parent, "QUALIDADE DA IMAGEM", 1)
        self._label(image, "Algoritmo de escala / filtro", size=9).grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.algo_combo = self._combo(image, self.algo_var, ALGORITHM_OPTIONS)
        self.algo_combo.grid(row=2, column=0, sticky="ew")
        sharp_line = tk.Frame(image, bg=COLORS["panel"])
        sharp_line.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        sharp_line.columnconfigure(0, weight=1)
        self._label(sharp_line, "Nitidez", bold=True).grid(row=0, column=0, sticky="w")
        self._label(sharp_line, textvariable=self.sharp_value_var, bold=True).grid(row=0, column=1, sticky="e")
        self.sharp_scale = self._slider(image, self.sharp_var, 0, 100)
        self.sharp_scale.grid(row=4, column=0, sticky="ew", pady=(6, 8))

        generation = self._section(parent, "GERAÇÃO DE QUADROS", 2)
        self.fg_check = self._toggle_row(generation, 1, "Interpolação de quadros",
                                        "Cria frames intermediários para mais fluidez.", self.fg_var)
        self.engine_combo = self._combo(generation, self.engine_var, ENGINE_OPTIONS)
        self.engine_combo.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        advanced = self._section(parent, "AJUSTES AVANÇADOS", 3)
        self.ultra_smooth_check = self._toggle_row(advanced, 1, "Ultra Smooth", "Maior precisão na interpolação.", self.ultra_smooth_var)
        self.perf_mode_check = self._toggle_row(advanced, 2, "Modo de desempenho", "Resolução interna de até 1280 × 720.", self.perf_mode_var)
        self.low_latency_check = self._toggle_row(advanced, 3, "Baixa latência", "Buffer menor para uma resposta mais rápida.", self.low_latency_var)

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
        self.list_label.config(text="Monitores detectados" if is_display else "Janelas detectadas")
        self.tree.heading("Title", text="Monitor" if is_display else "Título da janela")
        self.tree.heading("Process", text="Resolução / posição" if is_display else "Processo")
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
        self.source_count_var.set("1 fonte disponível" if count == 1 else f"{count} fontes disponíveis")
        if self.sources:
            self.empty_label.place_forget()
        else:
            self.empty_label.config(text="Nenhum monitor encontrado.\nConecte um monitor e atualize a lista." if is_display
                                    else "Nenhuma janela encontrada.\nAbra o jogo e atualize a lista.")
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
            self.selected_title_var.set("Nenhuma fonte selecionada")
            self.selected_detail_var.set("Selecione um item na lista para continuar.")
        else:
            title = source["title"]
            self.selected_title_var.set(title if len(title) <= 72 else title[:69] + "…")
            detail = source.get("process")
            if source.get("source_type") == "display":
                left, top, right, bottom = source["rect"]
                detail = f"{right - left} × {bottom - top}  ·  Monitor completo"
            self.selected_detail_var.set(detail)

    def _update_setting_display(self):
        fps = self.fps_var.get()
        self.fps_value_var.set(f"{fps} FPS")
        self.sharp_value_var.set(f"{self.sharp_var.get()}%")
        for value, button in self.fps_presets.items():
            button.config(bg=COLORS["accent_dim"] if fps == value else COLORS["input"])
        self.engine_combo.configure(state="readonly" if self.fg_var.get() else "disabled")
        scale = "Tela cheia" if self.scale_var.get() == "Fullscreen" else f"{self.scale_var.get()}×"
        generation = "Geração de quadros ativa" if self.fg_var.get() else "Somente escala / filtro"
        self.session_summary_var.set(f"{fps} FPS  ·  {scale}  ·  {generation}")

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
            self._set_save_status("Nenhuma alteração pendente", COLORS["success"])
            return
        self._set_save_status("Salvando preferências…", COLORS["accent"])
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
            self._set_save_status("Não foi possível salvar", COLORS["warning"])
            if notify:
                messagebox.showwarning(
                    "Não foi possível salvar as preferências",
                    "Os ajustes desta sessão podem não ser recuperados ao reabrir o app.\n\n"
                    f"Verifique a permissão de gravação em:\n{self.settings_store.path}\n\n{exc}",
                    parent=self.root,
                )
            return False
        self._last_saved_settings = settings
        self._set_save_status("Todas as preferências salvas", COLORS["success"])
        return True

    def _close_root(self):
        self._cancel_pending_save()
        self._closing = True
        self.root.destroy()

    def _on_close(self, event=None):
        if self._closing:
            return
        self._remember_selected_source()
        self._save_settings(notify=True)
        self._close_root()

    def _on_select(self, event=None):
        if self._closing:
            return "break"
        source = self._remember_selected_source()
        if not source:
            messagebox.showinfo("Selecione uma fonte", "Selecione uma janela ou um monitor na lista.", parent=self.root)
            return "break"
        settings = self._collect_settings()
        self.selected_source = {**source, **{key: value for key, value in settings.items()
                                          if key not in ("version", "preferred_sources", "source_type")}}
        # Flush the debounce before destroying Tk or initializing overlay/GPU resources.
        self._save_settings(notify=True)
        self._close_root()
        return "break"

    def get_selection(self):
        self.root.mainloop()
        return self.selected_source


if __name__ == "__main__":
    ui = GameSelectorUI()
    selection = ui.get_selection()
    print(f"User selected: {selection}")
