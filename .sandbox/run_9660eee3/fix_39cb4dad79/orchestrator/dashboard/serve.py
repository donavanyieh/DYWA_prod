from __future__ import annotations

import argparse
import errno
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from orchestrator.dashboard.build_bundle import write_dashboard_index


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = "/orchestrator/dashboard/index.html"


def make_server(
    *,
    host: str,
    port: int,
    directory: Path,
    port_attempts: int,
) -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
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
