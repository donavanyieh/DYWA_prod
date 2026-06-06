from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from uuid import uuid4

from shared.contracts.models import EventStatus, RunConfigV1, Stage0ResetResultV1
from shared.io import read_json, write_json
from shared.time import utc_now


ROOT = Path(__file__).resolve().parents[1]


def workspace_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def reset_stage0(
    run_id: str,
    config: RunConfigV1,
    output: Path | None = None,
) -> Stage0ResetResultV1:
    started_at = utc_now()
    restore_files = config.stage0.restore_files
    bug_seed = config.stage0.bug_seed

    restored_files: list[str] = []
    for item in restore_files:
        shutil.copyfile(workspace_path(item.source), workspace_path(item.target))
        restored_files.append(item.target)

    completed_at = utc_now()
    result = Stage0ResetResultV1(
        run_id=run_id,
        reset_id=f"reset_{uuid4().hex[:8]}",
        status=EventStatus.COMPLETED,
        started_at=started_at,
        completed_at=completed_at,
        restored_files=restored_files,
        bug_seed=bug_seed,
        error=None,
    )
    if output:
        write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore configured files to the Stage 0 buggy seed.")
    parser.add_argument("--run-id", default=f"run_{uuid4().hex[:8]}")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    config = RunConfigV1.model_validate(read_json(args.config))
    result = reset_stage0(args.run_id, config, args.output)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
