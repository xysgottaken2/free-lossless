"""Presentation backends for the overlay window.

pygame's default presentation is GDI: the window content is blitted by the CPU and
there is no Direct3D device anywhere, so a graphics hook such as ReShade has nothing
to attach to. Presenting through SDL's renderer gives the overlay a real D3D11
swapchain on Windows, which is the same thing Magpie and Lossless Scaling do — and
that is what lets ReShade installed next to the app hook this process.

The window is still SDL's, so everything else (click-through, always on top, capture
exclusion) keeps working: the Win32 handle is fetched from SDL itself.
"""
import ctypes
import sys

import pygame

try:  # the renderer lives in pygame's private SDL2 module
    from pygame._sdl2 import video as _video
except Exception:  # pragma: no cover - pygame without SDL2 bindings
    _video = None

import diagnostics

# Preferred renderer backends, in order. Direct3D 11 first: it is what ReShade hooks
# on Windows (its dxgi.dll wraps DXGI and the D3D11 device creation).
DRIVERS = ("d3d11", "d3d9", "opengl", "opengles2", "software")
GDI = "GDI"
D3D11 = "D3D11"
DISPLAY_MODES = (GDI, D3D11)


class SDLVersion(ctypes.Structure):
    _fields_ = [("major", ctypes.c_uint8), ("minor", ctypes.c_uint8), ("patch", ctypes.c_uint8)]


class SDL_WMInfo(ctypes.Structure):
    """The Windows member of SDL_SysWMinfo, which is the first member of its union."""
    _fields_ = [("version", SDLVersion), ("subsystem", ctypes.c_int),
                ("window", ctypes.c_void_p), ("hdc", ctypes.c_void_p),
                ("hinstance", ctypes.c_void_p)]


def _sdl_library():
    """The SDL2 library pygame already loaded, so the calls below hit the same state."""
    if _video is None:
        return None
    candidates = ["SDL2.dll", "SDL2"] if sys.platform == "win32" else [
        "libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so", "SDL2"]
    import os
    folders = [os.path.dirname(getattr(pygame, "__file__", "") or ""), os.getcwd()]
    # Frozen builds unpack next to the executable (onefile) or in _internal (onedir).
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        folders.append(bundle)
        folders.append(os.path.dirname(sys.executable))
    for name in candidates:
        for path in [name] + [os.path.join(folder, name) for folder in folders if folder]:
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
    return None


def _window_handle(sdl_window_id):
    """Win32 HWND of an SDL window, or None when it cannot be resolved."""
    if sys.platform != "win32" or not sdl_window_id:
        return None
    library = _sdl_library()
    if library is None:
        return None
    try:
        library.SDL_GetWindowFromID.argtypes = [ctypes.c_uint32]
        library.SDL_GetWindowFromID.restype = ctypes.c_void_p
        library.SDL_GetWindowWMInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(SDL_WMInfo)]
        library.SDL_GetWindowWMInfo.restype = ctypes.c_int
        library.SDL_GetVersion.argtypes = [ctypes.POINTER(SDLVersion)]
        window = library.SDL_GetWindowFromID(ctypes.c_uint32(int(sdl_window_id)))
        if not window:
            return None
        info = SDL_WMInfo()
        library.SDL_GetVersion(ctypes.byref(info.version))
        if not library.SDL_GetWindowWMInfo(window, ctypes.byref(info)):
            return None
        return int(info.window) if info.window else None
    except Exception:
        return None


class RendererDisplay:
    """Presents the overlay through SDL's renderer (Direct3D 11 on Windows).

    ``canvas`` is a plain pygame surface with the display size: the rest of the app
    draws into it exactly like it drew into the display surface, and ``present()``
    uploads it and flips the swapchain.
    """

    def __init__(self, title, size, drivers=DRIVERS):
        if _video is None:
            raise RuntimeError("pygame sem os módulos SDL2 (_sdl2)")
        available = [driver.name for driver in _video.get_drivers()]
        self.window = _video.Window(title, size=size, borderless=True)
        self.renderer = None
        self.driver = "?"
        errors = []
        # Try the preferred backends in order: a backend can be advertised and still
        # fail to initialise (no GL library, no D3D device), so ask, then insist.
        for name in drivers:
            if name not in available:
                continue
            try:
                self.renderer = _video.Renderer(self.window, available.index(name), -1, False, False)
                self.driver = name
                break
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if self.renderer is None:
            try:
                self.renderer = _video.Renderer(self.window, -1, -1, False, False)
                self.driver = available[0] if available else "?"
            except Exception as exc:
                errors.append(f"padrão: {exc}")
                try:
                    self.window.destroy()
                except Exception:
                    pass
                raise RuntimeError("; ".join(errors) or "nenhum renderizador SDL disponível")
        if errors:
            diagnostics.write_now("exibição", "backends de vídeo recusados: " + "; ".join(errors))
        self.canvas = pygame.Surface(size)
        self._texture = None
        self._size = size
        self._rebuild_texture()

    # ------------------------------------------------------------------ internals
    def _rebuild_texture(self):
        self._texture = _video.Texture.from_surface(self.renderer, self.canvas)
        self._texture.update(self.canvas)

    # -------------------------------------------------------------------- interface
    def present(self):
        self._texture.update(self.canvas)
        self.renderer.clear()
        self.renderer.blit(self._texture, pygame.Rect((0, 0), self._size))
        self.renderer.present()

    def resize(self, size):
        """Resize the window and the canvas, returning the new drawing surface."""
        if size == self._size:
            return self.canvas
        self.window.size = size
        self._size = size
        self.canvas = pygame.Surface(size)
        self._rebuild_texture()
        return self.canvas

    @property
    def size(self):
        return self._size

    def hwnd(self):
        """Win32 handle of the overlay window, for the click-through styles."""
        return _window_handle(getattr(self.window, "id", None))

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass


def create_display(mode, title, size, flags=pygame.NOFRAME):
    """Open the overlay window.

    Returns ``(surface, presenter, description)``. With ``GDI`` the presenter is None:
    the caller keeps using ``pygame.display.set_mode``/``flip`` as before. With
    ``D3D11`` the surface is the renderer canvas and the presenter flips it; any
    failure is reported instead of raised so the caller can fall back to GDI.
    """
    if mode == D3D11:
        display = RendererDisplay(title, size)
        return display.canvas, display, f"SDL renderer ({display.driver})"
    surface = pygame.display.set_mode(size, flags)
    pygame.display.set_caption(title)
    return surface, None, "GDI (pygame display)"


def describe(mode):
    return "D3D11 (SDL renderer)" if mode == D3D11 else "GDI (compatível)"
