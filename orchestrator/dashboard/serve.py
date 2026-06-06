from __future__ import annotations

import argparse
import errno
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from orchestrator.dashboard.build_bundle import write_dashboard_index


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = "/orchestrator/dashboard/index.html"
TRIGGER_RUN_PATH = "/api/trigger-run"
TRIGGER_LOG_PATH = "/api/trigger-log"
TRIGGER_STATUS_PATH = "/api/trigger-status"
RUN_LOCK = Lock()
RUN_PROCESS: subprocess.Popen[str] | None = None
RUN_STARTED_AT: str | None = None
RUN_LOG_PATH: Path | None = None
DEFAULT_LOG_TAIL_BYTES = 24_000
MAX_LOG_TAIL_BYTES = 200_000


def utc_timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_command() -> list[str]:
    override = os.environ.get("DASHBOARD_RUN_COMMAND")
    if override:
        return shlex.split(override)
    return [
        sys.executable,
        "-m",
        "orchestrator.run",
        "--mode",
        "live",
        "--config",
        "configs/run_config.json",
    ]


def trigger_status_payload() -> dict[str, object]:
    if RUN_PROCESS is None:
        return {"status": "idle"}

    return_code = RUN_PROCESS.poll()
    status = "running" if return_code is None else "completed"
    if return_code not in (None, 0):
        status = "failed"
    return {
        "status": status,
        "pid": RUN_PROCESS.pid,
        "return_code": return_code,
        "started_at": RUN_STARTED_AT,
        "log_path": str(RUN_LOG_PATH) if RUN_LOG_PATH else None,
    }


def read_log_tail(log_path: Path | None, max_bytes: int) -> tuple[str, int, bool]:
    if log_path is None or not log_path.exists():
        return "", 0, False

    file_size = log_path.stat().st_size
    start = max(file_size - max_bytes, 0)
    with log_path.open("rb") as log_file:
        log_file.seek(start)
        raw_content = log_file.read()

    text = raw_content.decode("utf-8", errors="replace")
    if start > 0:
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
    return text, file_size, start > 0


def trigger_log_payload(max_bytes: int = DEFAULT_LOG_TAIL_BYTES) -> dict[str, object]:
    payload = trigger_status_payload()
    text, size, truncated = read_log_tail(RUN_LOG_PATH, max_bytes)
    payload.update(
        {
            "text": text,
            "size": size,
            "truncated": truncated,
            "max_bytes": max_bytes,
        }
    )
    return payload


def start_run_process() -> dict[str, object]:
    global RUN_LOG_PATH
    global RUN_PROCESS
    global RUN_STARTED_AT

    command = run_command()
    log_dir = ROOT / "artifacts" / "dashboard_triggers"
    log_dir.mkdir(parents=True, exist_ok=True)
    RUN_STARTED_AT = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    RUN_LOG_PATH = log_dir / f"trigger_{utc_timestamp()}.log"
    with RUN_LOG_PATH.open("a") as log_file:
        RUN_PROCESS = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    payload = trigger_status_payload()
    payload["command"] = command
    return payload


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == TRIGGER_STATUS_PATH:
            with RUN_LOCK:
                self.send_json(trigger_status_payload())
            return
        if parsed.path == TRIGGER_LOG_PATH:
            requested_bytes = parse_qs(parsed.query).get("bytes", [str(DEFAULT_LOG_TAIL_BYTES)])[0]
            try:
                max_bytes = int(requested_bytes)
            except ValueError:
                max_bytes = DEFAULT_LOG_TAIL_BYTES
            max_bytes = min(max(max_bytes, 1_000), MAX_LOG_TAIL_BYTES)
            with RUN_LOCK:
                self.send_json(trigger_log_payload(max_bytes))
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != TRIGGER_RUN_PATH:
            self.send_json({"error": "Not found"}, status=404)
            return

        with RUN_LOCK:
            if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                payload = trigger_status_payload()
                payload["error"] = "A run is already in progress."
                self.send_json(payload, status=409)
                return

            try:
                payload = start_run_process()
            except OSError as error:
                self.send_json({"error": str(error)}, status=500)
                return

        self.send_json(payload, status=202)


def make_server(
    *,
    host: str,
    port: int,
    directory: Path,
    port_attempts: int,
) -> ThreadingHTTPServer:
    handler = partial(DashboardRequestHandler, directory=str(directory))
    attempts = 1 if port == 0 else port_attempts

    for offset in range(attempts):
        candidate_port = port + offset
        try:
            return ThreadingHTTPServer((host, candidate_port), handler)
        except OSError as error:
            if error.errno != errno.EADDRINUSE or offset == attempts - 1:
                raise

    raise RuntimeError("Could not start dashboard server.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and serve the dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--port-attempts", type=int, default=10)
    parser.add_argument("--artifacts-dir", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()

    index_path = write_dashboard_index(args.artifacts_dir)
    server = make_server(
        host=args.host,
        port=args.port,
        directory=ROOT,
        port_attempts=max(args.port_attempts, 1),
    )
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}{DASHBOARD_PATH}"

    print(f"Dashboard index: {index_path}", flush=True)
    print(f"Dashboard URL: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
