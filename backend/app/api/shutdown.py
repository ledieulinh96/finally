"""Shutdown signal for long-lived responses (SSE).

Uvicorn's graceful shutdown waits for every open connection to finish *before*
the lifespan ``finally`` runs, and it never tells an in-flight response that the
server is stopping. An open ``EventSource`` therefore blocks SIGTERM forever
(``docker stop`` then SIGKILLs after its timeout).

``install_signal_hooks`` chains a handler in front of whatever is installed for
SIGINT/SIGTERM (uvicorn's ``Server.handle_exit`` when called from the lifespan),
so the flag is set the moment the signal arrives; streams poll it and end, and
uvicorn's normal graceful shutdown proceeds.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable

HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ShutdownFlag:
    """Thread/signal-safe flag (a ``threading.Event`` — safe to set from a signal handler)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


def install_signal_hooks(flag: ShutdownFlag) -> Callable[[], None]:
    """Chain ``flag.set()`` before the current SIGINT/SIGTERM handlers.

    Returns a function restoring the previous handlers. No-op off the main
    thread (e.g. under TestClient), where signals can't be handled anyway.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    previous: dict[int, object] = {}

    def make_handler(prev):
        def handler(sig, frame):
            flag.set()
            if callable(prev):
                prev(sig, frame)
            elif prev == signal.SIG_DFL:
                signal.signal(sig, signal.SIG_DFL)
                signal.raise_signal(sig)

        return handler

    for sig in HANDLED_SIGNALS:
        prev = signal.getsignal(sig)
        previous[sig] = prev
        signal.signal(sig, make_handler(prev))

    def restore() -> None:
        for sig, prev in previous.items():
            if prev is not None:
                signal.signal(sig, prev)

    return restore
