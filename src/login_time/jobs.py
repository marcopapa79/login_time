"""Run slow work (portal API calls) off the Tk thread.

The worker function runs in a daemon thread and talks to the UI only through
emit(kind, payload); events are delivered on the Tk thread by polling a queue
with root.after(), because Tkinter widgets must never be touched from other threads.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Any, Callable

Emit = Callable[[str, Any], None]
_DONE = "__done__"


class JobRunner:
    def __init__(self, root: tk.Misc, poll_ms: int = 80) -> None:
        self.root = root
        self.poll_ms = poll_ms
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._on_event: Callable[[str, Any], None] | None = None
        self._on_finish: Callable[[Any, BaseException | None], None] | None = None
        self.label = ""

    @property
    def running(self) -> bool:
        return self._thread is not None

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def start(
        self,
        label: str,
        worker: Callable[[Emit, threading.Event], Any],
        *,
        on_event: Callable[[str, Any], None],
        on_finish: Callable[[Any, BaseException | None], None],
    ) -> bool:
        """Start a job. Returns False if another job is still running."""
        if self.running:
            return False
        self.label = label
        self._cancel.clear()
        self._on_event = on_event
        self._on_finish = on_finish

        def run() -> None:
            try:
                result = worker(lambda kind, payload=None: self._queue.put((kind, payload)), self._cancel)
                self._queue.put((_DONE, (result, None)))
            except BaseException as exc:  # noqa: BLE001 - delivered to on_finish on the UI thread
                self._queue.put((_DONE, (None, exc)))

        self._thread = threading.Thread(target=run, name=f"job:{label}", daemon=True)
        self._thread.start()
        self.root.after(self.poll_ms, self._poll)
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def _poll(self) -> None:
        finished: tuple[Any, BaseException | None] | None = None
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == _DONE:
                    finished = payload
                    break
                if self._on_event is not None:
                    self._on_event(kind, payload)
        except queue.Empty:
            pass

        if finished is None:
            try:
                self.root.after(self.poll_ms, self._poll)
            except tk.TclError:
                pass
            return

        on_finish = self._on_finish
        self._thread = None
        self._on_event = None
        self._on_finish = None
        if on_finish is not None:
            on_finish(*finished)
