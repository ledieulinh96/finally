"""Open SSE streams must not block graceful shutdown (SIGTERM / docker stop)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from app.api.shutdown import ShutdownFlag, install_signal_hooks

BACKEND = Path(__file__).resolve().parents[2]


def test_signal_hook_sets_flag_and_chains_previous():
    calls = []
    original = signal.signal(signal.SIGTERM, lambda s, f: calls.append(s))
    try:
        flag = ShutdownFlag()
        restore = install_signal_hooks(flag)
        signal.raise_signal(signal.SIGTERM)
        assert flag.is_set()
        assert calls == [signal.SIGTERM]  # uvicorn's handle_exit still runs
        restore()
        signal.raise_signal(signal.SIGTERM)
        assert calls == [signal.SIGTERM, signal.SIGTERM]
    finally:
        signal.signal(signal.SIGTERM, original)


def test_signal_hook_noop_off_main_thread():
    out = []
    t = threading.Thread(target=lambda: out.append(install_signal_hooks(ShutdownFlag())))
    t.start()
    t.join()
    out[0]()  # restore is a harmless no-op


def test_stream_ends_when_shutdown_flag_set(app, client):
    """An open stream finishes promptly once the app's shutdown flag is set.

    (TestClient buffers streamed bodies until the app finishes, so we set the
    flag from a timer and assert the request completes with the snapshot.)
    """
    timer = threading.Timer(1.0, app.state.shutdown.set)
    timer.start()
    start = time.monotonic()
    result: dict = {}

    def request():
        result["r"] = client.get("/api/stream/prices")

    t = threading.Thread(target=request, daemon=True)
    t.start()
    t.join(5)
    timer.cancel()
    assert not t.is_alive(), "SSE stream did not end after shutdown was signalled"
    assert time.monotonic() - start < 4
    r = result["r"]
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    lines = r.text.splitlines()
    assert lines[0] == "retry: 2000"
    assert sum(line.startswith("data:") for line in lines) >= 10  # full snapshot


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_live_sigterm_with_open_stream(tmp_path):
    """Real uvicorn + an open SSE client: SIGTERM exits quickly, lifespan shutdown runs."""
    port = _free_port()
    env = dict(os.environ, DB_PATH=str(tmp_path / "t.db"), SIM_SEED="1", LLM_MOCK="true")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--workers", "1"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start")

        stream = urllib.request.urlopen(f"{base}/api/stream/prices", timeout=10)
        assert stream.readline().startswith(b"retry:")

        start = time.monotonic()
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=5)
        assert time.monotonic() - start < 5
        log = server.stdout.read()
        assert "Application shutdown complete" in log
        assert "ERROR" not in log
        # The server closed the stream (EOF) rather than leaving it hanging.
        stream.read()
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
