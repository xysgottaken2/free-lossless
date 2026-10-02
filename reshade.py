"""ReShade support: find it, fetch it, and let the overlay be hooked by it.

The overlay presents through Direct3D 11 when the display mode is ``D3D11`` (see
d3d_display.py), which is what allows ReShade to attach to *this* process: ReShade
hooks DXGI/D3D11 inside the application it is installed on, exactly like it does for
Magpie or Lossless Scaling. The app only prepares the way — the DLL is copied into the
app folder by ReShade's own installer, never by us.

Nothing here touches the game: the game keeps whatever anti-cheat it has, and the
overlay only shows the image it already captures.
"""
import os
import re
import sys
import urllib.request
from pathlib import Path

import diagnostics

HOMEPAGE = "https://reshade.me/"
# reshade.me/downloads only serves the current release, so the URL is resolved from
# the home page instead of pinned: a pinned link dies the day a new version ships.
SETUP_PATTERN = re.compile(r'href="([^"]*ReShade_Setup_[\d.]+(?:_Addon)?\.exe)"', re.IGNORECASE)
# Files that prove ReShade is installed in a folder (any of the API wrappers plus the
# ini/shaders it creates on first run).
MARKER_FILES = ("ReShade.ini", "ReShade64.dll", "ReShade32.dll", "reshade-shaders",
                "dxgi.dll", "d3d11.dll", "d3d9.dll", "d3d12.dll", "opengl32.dll", "vulkan-1.dll")
USER_AGENT = "FreeLossless/1.0 (+ReShade setup helper)"


def app_directory():
    """Folder the app runs from: next to the executable, or the repo when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def detect(directory=None):
    """Names of the ReShade files present in ``directory`` (empty when not installed)."""
    directory = Path(directory) if directory else app_directory()
    try:
        if not directory.is_dir():
            return []
    except OSError:
        return []
    return sorted(name for name in MARKER_FILES if (directory / name).exists())


def is_installed(directory=None):
    return bool(detect(directory))


def marker_files(directory):
    """Files that show a ReShade installation in a game folder."""
    directory = Path(directory) if directory else None
    if not directory:
        return []
    try:
        if not directory.is_dir():
            return []
    except OSError:
        return []
    return [name for name in MARKER_FILES if (directory / name).exists()]


def installed_for_process(process_name):
    """Where ReShade is installed for a running game, if it can be found.

    Returns ``(directory, files)``, or ``(None, [])``. Best effort only: a game that
    cannot be inspected simply reports nothing.
    """
    if not process_name:
        return None, []
    try:
        import psutil

        wanted = str(process_name).lower()
        for process in psutil.process_iter(["name", "exe"]):
            name = (process.info.get("name") or "").lower()
            if name == wanted and process.info.get("exe"):
                directory = Path(process.info["exe"]).parent
                files = marker_files(directory)
                return (directory, files) if files else (None, [])
    except Exception:
        return None, []
    return None, []


def _open(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - fixed https host


def resolve_installer_url(opener=_open, timeout=20):
    """Current ReShade installer URL, read from the official home page.

    Returns ``(url, error)``. The plain build is preferred over the add-on one: the
    add-on build is for developers and needs a matching add-on system.
    """
    request = urllib.request.Request(HOMEPAGE, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as exc:
        return None, f"não foi possível abrir {HOMEPAGE}: {exc}"
    found = SETUP_PATTERN.findall(page)
    if not found:
        return None, "a página do ReShade não listou nenhum instalador"
    plain = [url for url in found if "_Addon" not in url]
    chosen = (plain or found)[0]
    if chosen.startswith("/"):
        chosen = HOMEPAGE.rstrip("/") + chosen
    elif not chosen.startswith("http"):
        chosen = HOMEPAGE + chosen.lstrip("./")
    return chosen, None


def _looks_like_windows_program(path):
    """ReShade's setup is a Windows executable: it must start with the PE magic."""
    try:
        if path.stat().st_size < 1_000_000:
            return False
        with path.open("rb") as stream:
            return stream.read(2) == b"MZ"
    except OSError:
        return False


def download_installer(directory=None, opener=_open, resolver=resolve_installer_url, timeout=180):
    """Download ReShade's setup into ``directory``; returns ``(path, error)``.

    A download that is not a Windows executable (an error page, a truncated file) is
    deleted instead of left behind pretending to be an installer.
    """
    directory = Path(directory) if directory else app_directory()
    url, error = resolver()
    if error:
        return None, error
    name = url.rsplit("/", 1)[-1] or "ReShade_Setup.exe"
    target = directory / name
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with opener(request, timeout) as response, target.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:
        target.unlink(missing_ok=True)
        return None, f"falha ao baixar o instalador: {exc}"
    if not _looks_like_windows_program(target):
        target.unlink(missing_ok=True)
        return None, "o arquivo baixado não é um instalador válido (verifique a conexão)"
    diagnostics.write_now("reshade", f"instalador do ReShade baixado em {target}")
    return target, None


def open_folder(path):
    """Show a file or folder in the system file manager; never raises."""
    try:
        target = Path(path)
        if sys.platform == "win32":
            if target.is_file():
                os.system(f'explorer /select,"{target}"')
            else:
                os.startfile(str(target))  # noqa: S606 - user-initiated
        elif sys.platform == "darwin":
            os.system(f'open "{target.parent if target.is_file() else target}"')
        else:
            os.system(f'xdg-open "{target.parent if target.is_file() else target}"')
        return True
    except Exception as exc:
        diagnostics.write_now("reshade", f"não foi possível abrir a pasta: {exc}")
        return False


def instructions(exe_name="FreeLossless.exe"):
    """What the user has to do with the installer, in the app's own words."""
    return (f"Execute o instalador e escolha {exe_name} na lista. Depois abra o overlay com o "
            f"modo de exibição D3D11: o ReShade passa a valer para a imagem do overlay.")
