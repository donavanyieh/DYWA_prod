from __future__ import annotations

import argparse
from pathlib import Path

from shared.ai.gpt5_client import OpenAIJsonClient
from shared.io import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one raw OpenAI JSON patch request.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    args = parser.parse_args()

    request = read_json(args.request)
    client = OpenAIJsonClient(
        model=str(request["model"]),
        reasoning_effort=request.get("reasoning_effort"),
        timeout_seconds=float(request["client_timeout_seconds"]),
    )
    response = client.create_json(
        instructions=str(request["instructions"]),
        prompt=str(request["prompt"]),
    )
    write_json(args.response, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
