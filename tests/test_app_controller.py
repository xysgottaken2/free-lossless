"""Start/Stop controller tests (requirement: Start starts, Stop ends)."""

from app_controller import (
    BUTTON_START,
    BUTTON_STOP,
    STATUS_RUNNING,
    STATUS_SELECT_WINDOW,
    STATUS_STOPPED,
    AppController,
)


class FakeUI:
    def __init__(self, selection=None):
        self.selection = selection
        self.states = []
        self.destroyed = False

    def collect_selection(self):
        return self.selection

    def show_state(self, button_text, status_text):
        self.states.append((button_text, status_text))

    def destroy(self):
        self.destroyed = True


class FakeHost:
    """Records pipeline calls; can stop itself during start (like the Stop button)."""

    def __init__(self, controller=None, stop_during_start=False):
        self.controller = controller
        self.stop_during_start = stop_during_start
        self.started = None
        self.stop_requests = 0
        self.saw_running_state = None

    def start_pipeline(self, selection):
        self.started = selection
        if self.controller is not None:
            self.saw_running_state = (self.controller.button_text, self.controller.status_text)
        if self.stop_during_start and self.controller is not None:
            self.controller.on_button_clicked()  # user clicks Stop mid-run
        return True

    def request_stop(self):
        self.stop_requests += 1


def test_button_labels_start_and_stop():
    controller = AppController()
    assert controller.button_text == BUTTON_START
    assert controller.status_text == STATUS_STOPPED

    controller.running = True
    assert controller.button_text == BUTTON_STOP
    assert controller.status_text == STATUS_RUNNING


def test_start_button_starts_pipeline():
    ui = FakeUI(selection={"source": "fullscreen", "monitor": 0})
    controller = AppController(host=None, ui=ui)
    host = FakeHost(controller=controller)
    controller.host = host

    controller.on_button_clicked()

    assert host.started == {"source": "fullscreen", "monitor": 0}
    # While running the button showed Stop / Running
    assert host.saw_running_state == (BUTTON_STOP, STATUS_RUNNING)
    # And the UI was told
    assert (BUTTON_STOP, STATUS_RUNNING) in ui.states
    # Pipeline returned -> back to Start / Stopped
    assert controller.button_text == BUTTON_START
    assert controller.status_text == STATUS_STOPPED
    assert ui.states[-1] == (BUTTON_START, STATUS_STOPPED)


def test_stop_button_stops_pipeline():
    ui = FakeUI(selection={"hwnd": 123, "source": "window"})
    controller = AppController(host=None, ui=ui)
    host = FakeHost(controller=controller, stop_during_start=True)
    controller.host = host

    controller.on_button_clicked()

    # The mid-run click flipped the running state and requested a stop
    assert host.stop_requests == 1
    assert host.started is not None
    assert controller.running is False
    assert controller.button_text == BUTTON_START


def test_start_requires_selection():
    ui = FakeUI(selection=None)
    host = FakeHost()
    controller = AppController(host=host, ui=ui)

    controller.on_button_clicked()

    assert host.started is None
    assert controller.running is False
    assert any(status == STATUS_SELECT_WINDOW for _, status in ui.states)


def test_double_start_is_guarded():
    controller = AppController(host=None, ui=None)

    class BlockingHost:
        calls = 0
        reentrant_result = "unset"

        def start_pipeline(self, selection):
            BlockingHost.calls += 1
            # Re-entrant start while running must be a no-op.
            BlockingHost.reentrant_result = controller.start()

        def request_stop(self):
            pass

    blocking = BlockingHost()
    controller.host = blocking
    controller.start()
    assert BlockingHost.calls == 1
    assert BlockingHost.reentrant_result is False


def test_works_without_ui():
    host = FakeHost()
    controller = AppController(host=host, ui=None)
    controller.on_button_clicked()
    assert host.started == {}


def test_close_while_running_requests_stop_then_destroys():
    ui = FakeUI(selection={"source": "window", "hwnd": 1})
    controller = AppController(host=None, ui=ui)

    class CloserHost(FakeHost):
        def start_pipeline(self, selection):
            super().start_pipeline(selection)
            controller.on_close()  # window closed while running

    host = CloserHost(controller=controller, stop_during_start=True)
    controller.host = host
    controller.on_button_clicked()

    assert host.stop_requests >= 1
    assert ui.destroyed is True


def test_close_when_idle_destroys_immediately():
    ui = FakeUI(selection=None)
    controller = AppController(host=None, ui=ui)
    controller.on_close()
    assert ui.destroyed is True
