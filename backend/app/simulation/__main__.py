"""Local fixture runner; does not create persisted versions or call external services."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.scene import ServiceScene
from app.schemas.simulation import SimulationSnapshot
from app.simulation.runner import SimulationError, parse_scene, run_demand_scenarios, simulate


def main() -> int:
    parser = argparse.ArgumentParser(description="Before Open deterministic fixture runner")
    parser.add_argument("scene_file", type=Path)
    parser.add_argument(
        "--scene-version-id", required=True, help="use demo-* IDs for local examples"
    )
    parser.add_argument("--scenario-label")
    parser.add_argument("--calculated-at", type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        scene = parse_scene(json.loads(args.scene_file.read_text()))
        timestamp = args.calculated_at if args.calculated_at is not None else datetime.now(UTC)
        runs: tuple[SimulationSnapshot, ...]
        if isinstance(scene, ServiceScene) or args.scenario_label is not None:
            runs = (
                simulate(
                    scene,
                    scene_version_id=args.scene_version_id,
                    scenario_label=args.scenario_label or "base",
                    calculated_at=timestamp,
                ),
            )
        else:
            runs = run_demand_scenarios(
                scene,
                scene_version_id=args.scene_version_id,
                calculated_at=timestamp,
            )
        print(
            json.dumps([run.model_dump(mode="json") for run in runs], ensure_ascii=False, indent=2)
        )
    except SimulationError as error:
        print(
            json.dumps(
                {"code": error.code, "validation": error.validation.model_dump()},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError):
        # Do not dump user input, notes or file contents in an error traceback.
        print(
            json.dumps({"code": "INVALID_INPUT", "message": "check scene file and arguments"}),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
