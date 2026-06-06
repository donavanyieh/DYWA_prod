from __future__ import annotations

from shared.time import utc_now


def log(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)

