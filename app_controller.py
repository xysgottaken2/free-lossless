"""Start/Stop controller for the Free Lossless pipeline.

Pure state machine between the Tk UI and the pipeline host
(``main.FrameGenerationApp``).  Keeps the button label / status text logic out
of the toolkit so it can be unit-tested without a display:

    [ Start ]  Status: Stopped   ->  [ Stop ]  Status: Running   ->  ...

The host must provide:

    start_pipeline(selection: dict)  - blocking until stopped (runs the overlay
                                       loop); must be safe to call once
    request_stop()                   - non-blocking; makes the loop exit
"""

from __future__ import annotations

from typing import Any, Optional

BUTTON_START = "Start"
BUTTON_STOP = "Stop"

STATUS_STOPPED = "Status: Stopped"
STATUS_RUNNING = "Status: Running"
STATUS_STOPPING = "Status: Stopping..."
STATUS_SELECT_WINDOW = "Status: Select a window first"
STATUS_FAILED = "Status: Failed to start"


class AppController:
    """Owns the Start/Stop state and the button/status text."""

    def __init__(self, host: Any = None, ui: Any = None):
        self.host = host
        self.ui = ui
        self.running = False
        self.close_requested = False

    # ------------------------------------------------------------------ UI
    def attach_ui(self, ui: Any) -> None:
        self.ui = ui

    @property
    def button_text(self) -> str:
        return BUTTON_STOP if self.running else BUTTON_START

    @property
    def status_text(self) -> str:
        return STATUS_RUNNING if self.running else STATUS_STOPPED

    def _sync_ui(self) -> None:
        if self.ui is not None:
            try:
                self.ui.show_state(self.button_text, self.status_text)
            except Exception:
                pass

    def show_message(self, message: str) -> None:
        if self.ui is not None:
            try:
                self.ui.show_state(self.button_text, message)
            except Exception:
                pass

    # ----------------------------------------------------------- lifecycle
    def on_button_clicked(self) -> None:
        """The big Start/Stop button."""
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self) -> bool:
        """Validate the selection and run the pipeline (blocking)."""
        if self.running:
            return False

        selection = self._collect_selection()
        if selection is None:
            self.show_message(STATUS_SELECT_WINDOW)
            return False

        self.running = True
        self._sync_ui()
        try:
            if self.host is not None:
                self.host.start_pipeline(selection)
        except Exception as exc:  # never let a crash kill the UI loop
            self.show_message(f"{STATUS_FAILED}: {exc}")
        finally:
            self.running = False
            self._sync_ui()
            self._after_stop()
        return True

    def stop(self) -> None:
        """Request the running pipeline to stop (non-blocking)."""
        if not self.running:
            return
        self.show_message(STATUS_STOPPING)
        if self.host is not None:
            try:
                self.host.request_stop()
            except Exception:
                pass

    def on_close(self) -> None:
        """Window close button: stop the pipeline if needed, then close."""
        self.close_requested = True
        if self.running:
            self.stop()
        else:
            self._destroy_ui()

    def _after_stop(self) -> None:
        if self.close_requested:
            self._destroy_ui()

    def _destroy_ui(self) -> None:
        if self.ui is not None:
            try:
                self.ui.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------- helpers
    def _collect_selection(self) -> Optional[dict]:
        if self.ui is None:
            return {}
        try:
            return self.ui.collect_selection()
        except Exception:
            return None
