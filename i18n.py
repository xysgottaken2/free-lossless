"""Small translation layer: English (US), Brazilian Portuguese and Simplified Chinese."""
import threading

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {
    "en": "English (US)",
    "pt-BR": "Português (Brasil)",
    "zh-CN": "简体中文",
}
LANGUAGES = tuple(LANGUAGE_NAMES)

_TRANSLATIONS = {
    "en": {
        "app.title": "Free Lossless",
        "app.subtitle": "More fluidity. Without modifying your game.",
        "save.autosave_on": "Auto-save enabled",
        "save.saving": "Saving preferences…",
        "save.saved": "All preferences saved",
        "save.nothing": "No pending changes",
        "save.failed": "Could not save",
        "save.unavailable": "Preferences unavailable; using defaults",
        "save.in_this_device": "Preferences saved on this device",
        "save.error_title": "Could not save preferences",
        "save.error_body": ("Changes from this session may not come back when you reopen the app.\n\n"
                            "Check write permission for:\n{path}\n\n{error}"),
        "source.section": "01  /  Capture source",
        "source.hint": "Choose a window or a monitor.",
        "source.window": "Window / game",
        "source.monitor": "Monitor",
        "source.windows_detected": "Windows detected",
        "source.monitors_detected": "Monitors detected",
        "source.window_title": "Window title",
        "source.process": "Process",
        "source.resolution_position": "Resolution / position",
        "source.count_one": "1 source available",
        "source.count_many": "{count} sources available",
        "source.refresh": "↻ Refresh",
        "source.empty_windows": "No windows found.\nOpen your game and refresh the list.",
        "source.empty_monitors": "No monitors found.\nConnect a monitor and refresh the list.",
        "source.none_selected": "No source selected",
        "source.select_hint": "Select an item in the list to continue.",
        "source.full_monitor": "Full monitor",
        "settings.section": "02  /  Overlay settings",
        "section.capture_output": "CAPTURE & OUTPUT",
        "section.image_quality": "IMAGE QUALITY",
        "section.frame_generation": "FRAME GENERATION",
        "section.advanced": "ADVANCED",
        "field.capture_backend": "Capture backend",
        "field.output_scale": "Output scale",
        "crash.failed_title": "Free Lossless stopped",
        "crash.failed_body": ("Free Lossless hit an error and had to close.\n\n"
                              "{error}\n\n"
                              "{memory}\n\n"
                              "Full details (with the traceback) were written to:\n{log}"),
        "startup.failed_title": "Free Lossless could not start",
        "startup.failed_body": ("Free Lossless could not load {module} and did not start.\n\n"
                                "{error}\n\n"
                                "{memory}\n\n"
                                "If the message mentions the paging file, raise the Windows virtual "
                                "memory: Settings > System > About > Advanced system settings > "
                                "Performance > Settings > Advanced > Virtual memory > Change, keep "
                                "\"Automatically manage paging file size\" on (or set a larger size), "
                                "then restart. Closing heavy programs (browser, other games) also frees "
                                "the memory Windows needs.\n\n"
                                "It is worth trying again: the app retries the load "
                                "{attempts} times before giving up, and it usually works once the "
                                "machine has room.\n\n"
                                "Full details (with the traceback) were written to:\n{log}"),
        "field.output_fps": "Output FPS",
        "fps.unlimited": "Unlimited (no vsync)",
        "fps.unlimited_value": "Unlimited",
        "fps.unlimited_hint": ("No output cap: the capture follows the game's real rate and the "
                               "generator adds the interpolated frames on top of it."),
        "field.sharpness": "Sharpness",
        "field.algorithm": "Scale / filter algorithm",
        "algo.bilinear": "Bilinear (fastest)",
        "algo.bicubic": "Bicubic (balanced)",
        "algo.lanczos": "Lanczos (sharpest, heavy)",
        "algo.fsr": "FSR 1.0 / CAS (adaptive sharpening)",
        "algo.ai": "NVIDIA AI SuperRes (GPU)",
        "algo.hint.bilinear": "Lightest option; softest image.",
        "algo.hint.bicubic": "Best balance for 1080p and above. Recommended.",
        "algo.hint.lanczos": "Sharpest, but several times heavier than Bicubic on large screens.",
        "algo.hint.fsr": "Fast upscale with adaptive sharpening.",
        "algo.hint.ai": "Maximum quality through the neural model; requires a capable GPU.",
        "field.internal_resolution": "Internal resolution",
        "internal.auto": "Auto (recommended)",
        "internal.performance": "Performance (800 × 600)",
        "internal.hd": "HD (1280 × 720)",
        "internal.fullhd": "Full HD (1920 × 1080)",
        "internal.native": "Native (source size)",
        "internal.hint": ("The resolution the filters work at, before the image goes to the screen. "
                          "Auto processes at the source size, so a fullscreen game is not shrunk and "
                          "blown up again; with the neural upscale it uses half the screen, because "
                          "the model doubles the frame. Lower values cost less and look softer."),
        "section.reshade": "RESHADE (D3D11)",
        "field.display_mode": "How the overlay draws",
        "display.gdi": "GDI (compatible, recommended)",
        "display.d3d11": "D3D11 (allows ReShade to hook the overlay)",
        "display.hint": ("ReShade hooks Direct3D, so it needs the overlay to draw with D3D11. If the "
                         "machine refuses, the overlay falls back to GDI by itself and says so in "
                         "the log."),
        "reshade.found": "ReShade found in the app folder ({files}): your effects apply to the overlay image.",
        "reshade.missing": "ReShade is not installed in the app folder.",
        "reshade.download": "Download ReShade installer",
        "reshade.downloading": "Downloading ReShade...",
        "reshade.downloaded": "Saved to {path}. Run it and pick {exe} in the list.",
        "reshade.failed": "Download failed: {error}",
        "section.filters": "EXTERNAL FILTERS (RESHADE STYLE)",
        "field.filter_preset": "Filter preset",
        "filter.off": "Off",
        "filter.soft": "Soft (LumaSharpen + Vibrance)",
        "filter.sharp": "Sharp (LumaSharpen + Clarity)",
        "filter.vivid": "Vivid (Vibrance + Contrast)",
        "filter.hint": ("Applied by the overlay to the final image, before the upscale: works in any "
                        "game, windowed or fullscreen, without touching the game. Costs a few "
                        "milliseconds per frame."),
        "filter.reshade_found": ("ReShade found in this game ({files}): the effects you use there "
                                 "already show up in the overlay image."),
        "toggle.filters": "Image filters (sharpening and upscale)",
        "toggle.filters_hint": ("Turn it off to see the raw image: no sharpening and a plain "
                                "resize, like turning frame interpolation off."),
        "filters.disabled": "Image filters are off in this session.",
        "toggle.interpolation": "Frame interpolation",
        "toggle.interpolation_hint": "Creates intermediate frames for more fluidity.",
        "toggle.ultra_smooth": "Ultra Smooth",
        "toggle.ultra_smooth_hint": "Higher interpolation precision.",
        "toggle.performance": "Performance mode",
        "toggle.performance_hint": "Internal resolution up to 1280 × 720.",
        "toggle.low_latency": "Low latency",
        "toggle.low_latency_hint": "Smaller buffer for a faster response.",
        "toggle.show_fps": "FPS counter on start",
        "toggle.show_fps_hint": "Shows the status panel as soon as the overlay opens.",
        "multiply.value": "x{multiplier}",
        "multiply.hint": "{extra} extra frame(s) per pair  ·  capture at {capture} FPS  ·  output at {fps} FPS",
        "multiply.hint_unlimited": ("{extra} extra frame(s) per pair  ·  capture at the game's rate  ·  "
                                    "output unlimited"),
        "multiply.warning": ("{extra} extra frame(s) per pair  ·  capture at {capture} FPS  ·  output at {fps} FPS"
                             "  ·  heavier on weak GPUs"),
        "multiply.disabled": "Enable frame interpolation to use frame generation.",
        "footer.summary": "{fps} FPS  ·  {scale}  ·  x{multiplier} interpolation",
        "footer.summary_unlimited": "Unlimited FPS  ·  {scale}  ·  x{multiplier} interpolation",
        "footer.summary_off": "{fps} FPS  ·  {scale}  ·  scale / filter only",
        "footer.fullscreen": "Fullscreen",
        "footer.shortcuts": "{stop} menu  ·  {fps} FPS  ·  {fsr} FSR  ·  Ctrl + Enter starts the overlay",
        "action.start": "Start overlay  →",
        "action.exit": "Exit",
        "action.settings": "⚙  Settings",
        "action.save": "Save",
        "action.cancel": "Cancel",
        "action.reset": "Restore defaults",
        "action.open_folder": "Open folder",
        "dialog.title": "Settings",
        "dialog.subtitle": "Global hotkeys and overlay preferences.",
        "dialog.hotkeys": "GLOBAL HOTKEYS",
        "dialog.overlay": "OVERLAY",
        "dialog.preferences": "PREFERENCES",
        "dialog.language": "Language",
        "dialog.language_hint": "Applied as soon as you save.",
        "dialog.preferences_file": "Preferences file (saved automatically):",
        "dialog.error_conflict": "Each hotkey needs a different key (F1–F12).",
        "dialog.error_ok": "Each hotkey uses its own key.",
        "dialog.hint_keys": "Esc cancels  ·  Enter saves",
        "dialog.conflict_title": "Repeated hotkeys",
        "dialog.conflict_body": "Choose a different key for each hotkey.",
        "hotkey.stop": "Stop the overlay (back to the menu)",
        "hotkey.fps": "Show / hide the FPS counter",
        "hotkey.fsr": "Toggle FSR / sharpening",
        "msg.select_source_title": "Select a source",
        "msg.select_source_body": "Select a window or a monitor in the list.",
        "msg.invalid_source": "The selected source has no valid area.",
        "msg.source_unavailable": "Source unavailable",
        "hud.menu": "menu",
        "hud.mode": "MODE",
        "hud.standard": "STD",
        "hud.smooth": "SMOOTH",
        "hud.live": "LIVE",
        "hud.generated": "FG",
        "splash.loading": "Loading…",
        "splash.slow": "Still loading, this can take a moment…",
        "selector.primary_monitor": "Display {number} (Primary monitor)",
        "selector.display": "Display {number}",
        "app.window_title": "Free Lossless — Overlay control",
        "field.frame_generation": "Frame generation",
        "mode.bitblt": "BitBlt (GDI, most compatible)",
        "mode.dxcam": "DXCAM (DXGI, fastest)",
        "engine.rife": "AI (RIFE ONNX)",
        "engine.fast": "Fast (DIS Flow)",
        "scale.fullscreen": "Fullscreen",
        "msg.display_disconnected": "The selected monitor was disconnected. Refresh the list.",
    },
    "pt-BR": {
        "app.title": "Free Lossless",
        "app.subtitle": "Mais fluidez. Sem modificar seu jogo.",
        "save.autosave_on": "Salvamento automático ativo",
        "save.saving": "Salvando preferências…",
        "save.saved": "Todas as preferências salvas",
        "save.nothing": "Nenhuma alteração pendente",
        "save.failed": "Não foi possível salvar",
        "save.unavailable": "Preferências indisponíveis; usando padrão",
        "save.in_this_device": "Preferências salvas neste dispositivo",
        "save.error_title": "Não foi possível salvar as preferências",
        "save.error_body": ("Os ajustes desta sessão podem não ser recuperados ao reabrir o app.\n\n"
                            "Verifique a permissão de gravação em:\n{path}\n\n{error}"),
        "source.section": "01  /  Fonte de captura",
        "source.hint": "Escolha uma janela ou um monitor.",
        "source.window": "Janela / jogo",
        "source.monitor": "Monitor",
        "source.windows_detected": "Janelas detectadas",
        "source.monitors_detected": "Monitores detectados",
        "source.window_title": "Título da janela",
        "source.process": "Processo",
        "source.resolution_position": "Resolução / posição",
        "source.count_one": "1 fonte disponível",
        "source.count_many": "{count} fontes disponíveis",
        "source.refresh": "↻ Atualizar",
        "source.empty_windows": "Nenhuma janela encontrada.\nAbra o jogo e atualize a lista.",
        "source.empty_monitors": "Nenhum monitor encontrado.\nConecte um monitor e atualize a lista.",
        "source.none_selected": "Nenhuma fonte selecionada",
        "source.select_hint": "Selecione um item na lista para continuar.",
        "source.full_monitor": "Monitor completo",
        "settings.section": "02  /  Ajustes do overlay",
        "section.capture_output": "CAPTURA E SAÍDA",
        "section.image_quality": "QUALIDADE DA IMAGEM",
        "section.frame_generation": "GERAÇÃO DE QUADROS",
        "section.advanced": "AJUSTES AVANÇADOS",
        "field.capture_backend": "Backend de captura",
        "field.output_scale": "Escala de saída",
        "crash.failed_title": "O Free Lossless parou",
        "crash.failed_body": ("O Free Lossless encontrou um erro e precisou fechar.\n\n"
                              "{error}\n\n"
                              "{memory}\n\n"
                              "Os detalhes completos (com o traceback) foram gravados em:\n{log}"),
        "startup.failed_title": "O Free Lossless não conseguiu iniciar",
        "startup.failed_body": ("O Free Lossless não conseguiu carregar {module} e não iniciou.\n\n"
                                "{error}\n\n"
                                "{memory}\n\n"
                                "Se a mensagem falar do arquivo de paginação, aumente a memória "
                                "virtual do Windows: Configurações > Sistema > Sobre > Configurações "
                                "avançadas do sistema > Desempenho > Configurações > Avançado > Memória "
                                "virtual > Alterar, deixe \"Gerenciar automaticamente o tamanho do "
                                "arquivo de paginação\" ligado (ou defina um tamanho maior) e reinicie. "
                                "Fechar programas pesados (navegador, outros jogos) também libera a "
                                "memória de que o Windows precisa.\n\n"
                                "Vale tentar de novo: o app tenta carregar {attempts} vezes antes de "
                                "desistir, e costuma dar certo quando a máquina tem folga.\n\n"
                                "Os detalhes completos (com o traceback) foram gravados em:\n{log}"),
        "field.output_fps": "FPS de saída",
        "fps.unlimited": "Ilimitado (sem vsync)",
        "fps.unlimited_value": "Ilimitado",
        "fps.unlimited_hint": ("Sem teto de saída: a captura acompanha a taxa real do jogo e o gerador "
                               "soma os quadros interpolados por cima dela."),
        "field.sharpness": "Nitidez",
        "field.algorithm": "Algoritmo de escala / filtro",
        "algo.bilinear": "Bilinear (mais rápido)",
        "algo.bicubic": "Bicúbico (equilibrado)",
        "algo.lanczos": "Lanczos (mais nítido, pesado)",
        "algo.fsr": "FSR 1.0 / CAS (nitidez adaptativa)",
        "algo.ai": "NVIDIA AI SuperRes (GPU)",
        "algo.hint.bilinear": "Opção mais leve; imagem mais suave.",
        "algo.hint.bicubic": "Melhor equilíbrio em 1080p ou mais. Recomendado.",
        "algo.hint.lanczos": "Mais nítido, mas várias vezes mais pesado que o bicúbico em telas grandes.",
        "algo.hint.fsr": "Escala rápida com nitidez adaptativa.",
        "algo.hint.ai": "Qualidade máxima pelo modelo neural; exige uma GPU capaz.",
        "field.internal_resolution": "Resolução interna",
        "internal.auto": "Auto (recomendado)",
        "internal.performance": "Desempenho (800 × 600)",
        "internal.hd": "HD (1280 × 720)",
        "internal.fullhd": "Full HD (1920 × 1080)",
        "internal.native": "Nativa (tamanho da fonte)",
        "internal.hint": ("Resolução em que os filtros trabalham, antes de a imagem ir para a tela. "
                          "Em Auto o processamento acontece no tamanho da fonte, então um jogo em "
                          "tela cheia não é reduzido e ampliado de novo; com o upscale neural ele "
                          "usa metade da tela, porque o modelo dobra o quadro. Valores menores "
                          "custam menos e ficam mais suaves."),
        "section.reshade": "RESHADE (D3D11)",
        "field.display_mode": "Como o overlay desenha",
        "display.gdi": "GDI (compatível, recomendado)",
        "display.d3d11": "D3D11 (permite o ReShade hookar o overlay)",
        "display.hint": ("O ReShade hooka Direct3D, então precisa que o overlay desenhe em D3D11. Se a "
                         "máquina recusar, o overlay cai para GDI sozinho e registra o motivo no log."),
        "reshade.found": "ReShade encontrado na pasta do app ({files}): seus efeitos valem para a imagem do overlay.",
        "reshade.missing": "ReShade não está instalado na pasta do app.",
        "reshade.download": "Baixar instalador do ReShade",
        "reshade.downloading": "Baixando o ReShade...",
        "reshade.downloaded": "Salvo em {path}. Execute e escolha {exe} na lista.",
        "reshade.failed": "Falha no download: {error}",
        "section.filters": "FILTROS EXTERNOS (ESTILO RESHADE)",
        "field.filter_preset": "Preset de filtros",
        "filter.off": "Desligado",
        "filter.soft": "Suave (LumaSharpen + Vibrance)",
        "filter.sharp": "Nítido (LumaSharpen + Clarity)",
        "filter.vivid": "Vívido (Vibrance + Contraste)",
        "filter.hint": ("Aplicados pelo overlay na imagem final, antes do upscale: funcionam em "
                        "qualquer jogo, em janela ou tela cheia, sem tocar no jogo. Custa alguns "
                        "milissegundos por quadro."),
        "filter.reshade_found": ("ReShade encontrado neste jogo ({files}): os efeitos que você usa "
                                 "lá já aparecem na imagem do overlay."),
        "toggle.filters": "Filtros de imagem (nitidez e upscale)",
        "toggle.filters_hint": ("Desligue para ver a imagem crua: sem nitidez e com redimensionamento "
                                "simples, como desligar a interpolação de quadros."),
        "filters.disabled": "Os filtros de imagem estão desligados nesta sessão.",
        "toggle.interpolation": "Interpolação de quadros",
        "toggle.interpolation_hint": "Cria frames intermediários para mais fluidez.",
        "toggle.ultra_smooth": "Ultra Smooth",
        "toggle.ultra_smooth_hint": "Maior precisão na interpolação.",
        "toggle.performance": "Modo de desempenho",
        "toggle.performance_hint": "Resolução interna de até 1280 × 720.",
        "toggle.low_latency": "Baixa latência",
        "toggle.low_latency_hint": "Buffer menor para uma resposta mais rápida.",
        "toggle.show_fps": "Contador de FPS ao iniciar",
        "toggle.show_fps_hint": "Mostra o painel de status assim que o overlay abre.",
        "multiply.value": "x{multiplier}",
        "multiply.hint": "{extra} frame(s) extra por par  ·  captura a {capture} FPS  ·  saída a {fps} FPS",
        "multiply.hint_unlimited": ("{extra} frame(s) extra por par  ·  captura na taxa do jogo  ·  "
                                    "saída ilimitada"),
        "multiply.warning": ("{extra} frame(s) extra por par  ·  captura a {capture} FPS  ·  saída a {fps} FPS"
                             "  ·  pesa mais em GPUs fracas"),
        "multiply.disabled": "Ative a interpolação de quadros para usar a geração de frames.",
        "footer.summary": "{fps} FPS  ·  {scale}  ·  x{multiplier} interpolação",
        "footer.summary_unlimited": "FPS ilimitado  ·  {scale}  ·  x{multiplier} interpolação",
        "footer.summary_off": "{fps} FPS  ·  {scale}  ·  somente escala / filtro",
        "footer.fullscreen": "Tela cheia",
        "footer.shortcuts": "{stop} menu  ·  {fps} FPS  ·  {fsr} FSR  ·  Ctrl + Enter inicia o overlay",
        "action.start": "Iniciar overlay  →",
        "action.exit": "Sair",
        "action.settings": "⚙  Configurações",
        "action.save": "Salvar",
        "action.cancel": "Cancelar",
        "action.reset": "Restaurar padrões",
        "action.open_folder": "Abrir pasta",
        "dialog.title": "Configurações",
        "dialog.subtitle": "Atalhos globais e preferências do overlay.",
        "dialog.hotkeys": "ATALHOS GLOBAIS",
        "dialog.overlay": "OVERLAY",
        "dialog.preferences": "PREFERÊNCIAS",
        "dialog.language": "Idioma",
        "dialog.language_hint": "Aplicado assim que você salvar.",
        "dialog.preferences_file": "Arquivo de preferências (salvo automaticamente):",
        "dialog.error_conflict": "Cada atalho precisa de uma tecla diferente (F1–F12).",
        "dialog.error_ok": "Cada atalho usa uma tecla diferente.",
        "dialog.hint_keys": "Esc cancela  ·  Enter salva",
        "dialog.conflict_title": "Atalhos repetidos",
        "dialog.conflict_body": "Escolha uma tecla diferente para cada atalho.",
        "hotkey.stop": "Parar o overlay (voltar ao menu)",
        "hotkey.fps": "Mostrar / ocultar o contador de FPS",
        "hotkey.fsr": "Alternar FSR / nitidez",
        "msg.select_source_title": "Selecione uma fonte",
        "msg.select_source_body": "Selecione uma janela ou um monitor na lista.",
        "msg.invalid_source": "A fonte selecionada não tem uma área válida.",
        "msg.source_unavailable": "Fonte indisponível",
        "hud.menu": "menu",
        "hud.mode": "MODO",
        "hud.standard": "PADRÃO",
        "hud.smooth": "SMOOTH",
        "hud.live": "LIVE",
        "hud.generated": "FG",
        "splash.loading": "Carregando…",
        "splash.slow": "Ainda carregando, isso pode levar um instante…",
        "selector.primary_monitor": "Display {number} (Monitor principal)",
        "selector.display": "Display {number}",
        "app.window_title": "Free Lossless — Controle de overlay",
        "field.frame_generation": "Geração de frames",
        "mode.bitblt": "BitBlt (GDI, mais compatível)",
        "mode.dxcam": "DXCAM (DXGI, mais rápido)",
        "engine.rife": "AI (RIFE ONNX)",
        "engine.fast": "Rápido (DIS Flow)",
        "scale.fullscreen": "Tela cheia",
        "msg.display_disconnected": "O monitor selecionado foi desconectado. Atualize a lista.",
    },
    "zh-CN": {
        "app.title": "Free Lossless",
        "app.subtitle": "更流畅，无需修改游戏。",
        "save.autosave_on": "已开启自动保存",
        "save.saving": "正在保存偏好设置…",
        "save.saved": "所有偏好设置已保存",
        "save.nothing": "没有待保存的更改",
        "save.failed": "无法保存",
        "save.unavailable": "偏好设置不可用，正在使用默认值",
        "save.in_this_device": "偏好设置已保存在本设备",
        "save.error_title": "无法保存偏好设置",
        "save.error_body": "本次会话的更改在重新打开应用后可能不会保留。\n\n请检查以下位置的写入权限：\n{path}\n\n{error}",
        "source.section": "01  /  捕获源",
        "source.hint": "选择窗口或显示器。",
        "source.window": "窗口 / 游戏",
        "source.monitor": "显示器",
        "source.windows_detected": "检测到的窗口",
        "source.monitors_detected": "检测到的显示器",
        "source.window_title": "窗口标题",
        "source.process": "进程",
        "source.resolution_position": "分辨率 / 位置",
        "source.count_one": "1 个可用来源",
        "source.count_many": "{count} 个可用来源",
        "source.refresh": "↻ 刷新",
        "source.empty_windows": "未找到窗口。\n请打开游戏并刷新列表。",
        "source.empty_monitors": "未找到显示器。\n请连接显示器并刷新列表。",
        "source.none_selected": "未选择来源",
        "source.select_hint": "请在列表中选择一项以继续。",
        "source.full_monitor": "完整显示器",
        "settings.section": "02  /  叠加层设置",
        "section.capture_output": "捕获与输出",
        "section.image_quality": "图像质量",
        "section.frame_generation": "帧生成",
        "section.advanced": "高级设置",
        "field.capture_backend": "捕获后端",
        "field.output_scale": "输出缩放",
        "crash.failed_title": "Free Lossless 已停止",
        "crash.failed_body": ("Free Lossless 遇到错误，只能关闭。\n\n"
                              "{error}\n\n"
                              "{memory}\n\n"
                              "完整信息（含调试堆栈）已写入：\n{log}"),
        "startup.failed_title": "Free Lossless 无法启动",
        "startup.failed_body": ("Free Lossless 无法加载 {module}，启动失败。\n\n"
                                "{error}\n\n"
                                "{memory}\n\n"
                                "如果提示与分页文件有关，请增大 Windows 虚拟内存：设置 > 系统 > 关于 > "
                                "高级系统设置 > 性能 > 设置 > 高级 > 虚拟内存 > 更改，保持“自动管理分页文件"
                                "大小”（或设置更大的值），然后重启电脑。关闭占用较大的程序（浏览器、其他"
                                "游戏）也能释放 Windows 所需的内存。\n\n"
                                "可以再试一次：应用在放弃前会重试 {attempts} 次，机器有余量时通常就能成功。\n\n"
                                "完整信息（含调试堆栈）已写入：\n{log}"),
        "field.output_fps": "输出帧率",
        "fps.unlimited": "无限制（关闭垂直同步）",
        "fps.unlimited_value": "无限制",
        "fps.unlimited_hint": "输出不设上限：采集跟随游戏的真实帧率，生成器在此之上补充插值帧。",
        "field.sharpness": "锐化",
        "field.algorithm": "缩放 / 滤镜算法",
        "algo.bilinear": "双线性（最快）",
        "algo.bicubic": "双三次（均衡）",
        "algo.lanczos": "Lanczos（最锐利，较重）",
        "algo.fsr": "FSR 1.0 / CAS（自适应锐化）",
        "algo.ai": "NVIDIA AI SuperRes（GPU）",
        "algo.hint.bilinear": "最轻量的选项，画面较柔和。",
        "algo.hint.bicubic": "1080p 及以上的最佳平衡，推荐。",
        "algo.hint.lanczos": "最锐利，但在大屏幕上比双三次慢数倍。",
        "algo.hint.fsr": "快速放大并带有自适应锐化。",
        "algo.hint.ai": "通过神经网络模型获得最佳质量，需要性能较强的 GPU。",
        "field.internal_resolution": "内部处理分辨率",
        "internal.auto": "自动（推荐）",
        "internal.performance": "性能（800 × 600）",
        "internal.hd": "HD（1280 × 720）",
        "internal.fullhd": "全高清（1920 × 1080）",
        "internal.native": "原生（源尺寸）",
        "internal.hint": ("滤镜处理画面时使用的分辨率。自动模式下按源尺寸处理，全屏游戏不会被缩小后再放大；"
                          "使用神经网络放大时取屏幕的一半，因为模型会把画面放大一倍。数值越低越省性能，画面越柔和。"),
        "section.reshade": "RESHADE（D3D11）",
        "field.display_mode": "叠加层绘制方式",
        "display.gdi": "GDI（兼容，推荐）",
        "display.d3d11": "D3D11（允许 ReShade 挂钩叠加层）",
        "display.hint": "ReShade 挂钩 Direct3D，因此叠加层需用 D3D11 绘制。若机器不支持，会自动回退到 GDI 并写入日志。",
        "reshade.found": "在应用目录中发现 ReShade（{files}）：你的效果会作用于叠加画面。",
        "reshade.missing": "应用目录中未安装 ReShade。",
        "reshade.download": "下载 ReShade 安装程序",
        "reshade.downloading": "正在下载 ReShade…",
        "reshade.downloaded": "已保存到 {path}。运行它并在列表中选择 {exe}。",
        "reshade.failed": "下载失败：{error}",
        "section.filters": "外部滤镜（ReShade 风格）",
        "field.filter_preset": "滤镜预设",
        "filter.off": "关闭",
        "filter.soft": "柔和（LumaSharpen + Vibrance）",
        "filter.sharp": "锐利（LumaSharpen + Clarity）",
        "filter.vivid": "鲜艳（Vibrance + 对比度）",
        "filter.hint": ("由叠加层在放大前应用于最终画面：窗口或全屏游戏都能用，不接触游戏进程。"
                        "每个画面约几毫秒。"),
        "filter.reshade_found": "检测到该游戏已安装 ReShade（{files}）：你在那里使用的效果已经出现在叠加画面中。",
        "toggle.filters": "图像滤镜（锐化与放大）",
        "toggle.filters_hint": "关闭后显示原始画面：不锐化，仅做简单缩放，就像关闭帧插值一样。",
        "filters.disabled": "本次会话已关闭图像滤镜。",
        "toggle.interpolation": "帧插值",
        "toggle.interpolation_hint": "生成中间帧以提升流畅度。",
        "toggle.ultra_smooth": "Ultra Smooth",
        "toggle.ultra_smooth_hint": "更高的插值精度。",
        "toggle.performance": "性能模式",
        "toggle.performance_hint": "内部渲染分辨率最高 1280 × 720。",
        "toggle.low_latency": "低延迟",
        "toggle.low_latency_hint": "更小的缓冲，响应更快。",
        "toggle.show_fps": "启动时显示 FPS 计数",
        "toggle.show_fps_hint": "叠加层打开后立即显示状态面板。",
        "multiply.value": "x{multiplier}",
        "multiply.hint": "每对帧额外生成 {extra} 帧  ·  以 {capture} FPS 捕获  ·  输出 {fps} FPS",
        "multiply.hint_unlimited": "每对帧额外生成 {extra} 帧  ·  采集跟随游戏帧率  ·  输出无限制",
        "multiply.warning": "每对帧额外生成 {extra} 帧  ·  以 {capture} FPS 捕获  ·  输出 {fps} FPS  ·  对低端 GPU 负担较重",
        "multiply.disabled": "启用帧插值后即可使用帧生成。",
        "footer.summary": "{fps} FPS  ·  {scale}  ·  x{multiplier} 插值",
        "footer.summary_unlimited": "帧率无限制  ·  {scale}  ·  x{multiplier} 插值",
        "footer.summary_off": "{fps} FPS  ·  {scale}  ·  仅缩放 / 滤镜",
        "footer.fullscreen": "全屏",
        "footer.shortcuts": "{stop} 菜单  ·  {fps} FPS  ·  {fsr} FSR  ·  Ctrl + Enter 启动叠加层",
        "action.start": "启动叠加层  →",
        "action.exit": "退出",
        "action.settings": "⚙  设置",
        "action.save": "保存",
        "action.cancel": "取消",
        "action.reset": "恢复默认",
        "action.open_folder": "打开文件夹",
        "dialog.title": "设置",
        "dialog.subtitle": "全局快捷键与叠加层偏好。",
        "dialog.hotkeys": "全局快捷键",
        "dialog.overlay": "叠加层",
        "dialog.preferences": "偏好设置",
        "dialog.language": "语言",
        "dialog.language_hint": "保存后立即生效。",
        "dialog.preferences_file": "偏好设置文件（自动保存）：",
        "dialog.error_conflict": "每个快捷键需要使用不同的按键（F1–F12）。",
        "dialog.error_ok": "每个快捷键使用不同的按键。",
        "dialog.hint_keys": "Esc 取消  ·  Enter 保存",
        "dialog.conflict_title": "快捷键重复",
        "dialog.conflict_body": "请为每个快捷键选择不同的按键。",
        "hotkey.stop": "停止叠加层（返回菜单）",
        "hotkey.fps": "显示 / 隐藏 FPS 计数",
        "hotkey.fsr": "切换 FSR / 锐化",
        "msg.select_source_title": "请选择来源",
        "msg.select_source_body": "请在列表中选择窗口或显示器。",
        "msg.invalid_source": "所选来源没有有效区域。",
        "msg.source_unavailable": "来源不可用",
        "hud.menu": "菜单",
        "hud.mode": "模式",
        "hud.standard": "标准",
        "hud.smooth": "平滑",
        "hud.live": "实时",
        "hud.generated": "生成",
        "splash.loading": "正在加载…",
        "splash.slow": "仍在加载，请稍候…",
        "selector.primary_monitor": "显示器 {number}（主显示器）",
        "selector.display": "显示器 {number}",
        "app.window_title": "Free Lossless — 叠加层控制",
        "field.frame_generation": "帧生成",
        "mode.bitblt": "BitBlt（GDI，兼容性最好）",
        "mode.dxcam": "DXCAM（DXGI，最快）",
        "engine.rife": "AI（RIFE ONNX）",
        "engine.fast": "快速（DIS Flow）",
        "scale.fullscreen": "全屏",
        "msg.display_disconnected": "所选显示器已断开连接。请刷新列表。",
    },
}

_lock = threading.Lock()
_current_language = DEFAULT_LANGUAGE


def normalize_language(code):
    """Map anything unknown to the default language, so startup always works."""
    if isinstance(code, str):
        if code in _TRANSLATIONS:
            return code
        for known in LANGUAGES:
            if code.casefold() == known.casefold():
                return known
    return DEFAULT_LANGUAGE


def set_language(code):
    global _current_language
    with _lock:
        _current_language = normalize_language(code)
    return _current_language


def get_language():
    with _lock:
        return _current_language


def language_name(code):
    return LANGUAGE_NAMES.get(normalize_language(code), LANGUAGE_NAMES[DEFAULT_LANGUAGE])


def language_code(display_name):
    """Turn a name picked in the menu ("简体中文") back into its code ("zh-CN")."""
    for code, name in LANGUAGE_NAMES.items():
        if name == display_name:
            return code
    return normalize_language(display_name)


def translate(key, language=None, **fields):
    """Look the key up in the requested language, falling back to English."""
    table = _TRANSLATIONS[normalize_language(language or get_language())]
    template = table.get(key) or _TRANSLATIONS[DEFAULT_LANGUAGE].get(key) or key
    if not fields:
        return template
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return template
