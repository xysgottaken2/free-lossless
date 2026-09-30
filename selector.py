import win32gui
import win32process
import psutil

class WindowSelector:
    @staticmethod
    def get_visible_windows():
        """
        Returns a list of visible windows with their titles and HWNDs.
        """
        def enum_handler(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    # Get process name
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        process = psutil.Process(pid)
                        proc_name = process.name()
                        windows.append({"hwnd": hwnd, "title": title, "process": proc_name})
                    except:
                        pass
        
        windows = []
        win32gui.EnumWindows(enum_handler, windows)
        return windows

    @staticmethod
    def get_window_rect(hwnd):
        """
        Returns the (left, top, right, bottom) of the window.
        """
        return win32gui.GetWindowRect(hwnd)



class DisplaySelector:
    @staticmethod
    def get_displays():
        """List active monitors using Windows display numbers and desktop coordinates."""
        import win32api
        import re

        displays = []
        for handle, _, _ in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(handle)
            device = info["Device"]
            match = re.search(r"DISPLAY(\d+)$", device)
            number = int(match.group(1)) if match else len(displays) + 1
            primary = bool(info["Flags"] & 1)  # MONITORINFOF_PRIMARY
            displays.append({
                "source_type": "display",
                "device": device,
                "number": number,
                "title": f"Display {number}" + (" (Monitor principal)" if primary else ""),
                "primary": primary,
                "rect": tuple(info["Monitor"]),
            })
        return sorted(displays, key=lambda display: display["number"])

    @staticmethod
    def get_display_rect(device):
        for display in DisplaySelector.get_displays():
            if display["device"] == device:
                return display["rect"]
        raise ValueError("O monitor selecionado foi desconectado. Atualize a lista.")


def get_source_rect(source):
    if source.get("source_type", "window") == "display":
        return DisplaySelector.get_display_rect(source["device"])
    return WindowSelector.get_window_rect(source["hwnd"])


def get_source_monitor_rect(source):
    """Fullscreen always uses the selected source's monitor, not the primary."""
    if source.get("source_type", "window") == "display":
        return get_source_rect(source)
    import win32api
    monitor = win32api.MonitorFromWindow(source["hwnd"], 2)  # MONITOR_DEFAULTTONEAREST
    return tuple(win32api.GetMonitorInfo(monitor)["Monitor"])


if __name__ == "__main__":
    selector = WindowSelector()
    wins = selector.get_visible_windows()
    print("Visible Windows:")
    for i, w in enumerate(wins):
        print(f"[{i}] {w['title']} ({w['process']})")
