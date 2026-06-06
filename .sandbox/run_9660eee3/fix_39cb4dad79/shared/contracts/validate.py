from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from shared.contracts.registry import model_for_path


def iter_json_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(target.rglob("*.json"))


def validate_file(path: Path) -> str:
    data = json.loads(path.read_text())
    model = model_for_path(path)
    model.model_validate(data)
    return model.__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate contract JSON payloads.")
    parser.add_argument("target", type=Path, help="JSON file or directory of JSON files")
    args = parser.parse_args()

    failures: list[str] = []
    for path in iter_json_files(args.target):
        should_be_invalid = ".invalid" in path.name
        try:
            model_name = validate_file(path)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            if should_be_invalid:
                print(f"PASS invalid {path}: rejected as expected")
                continue
            failures.append(f"FAIL {path}: {exc}")
            continue

        if should_be_invalid:
            failures.append(f"FAIL {path}: expected invalid payload, but it passed")
        else:
            print(f"PASS {path}: {model_name}")

    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

