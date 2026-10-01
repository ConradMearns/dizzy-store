"""Scenario runner bridge — one pytest case per scenarios/<name>/scenario.yaml.

Each scenario runs against a simulated cluster of REAL devices (real procedures,
projections, queries, policies, DAG replication); only the network and the clock
are simulated. Failures report in scenario vocabulary — step number, claim,
what differed — never a traceback. Format: scenarios/AUTHORING.md.

    uv run --project store pytest store/tests/test_scenarios.py -k evict
"""
from pathlib import Path

import pytest

from dizzy_store.scenario import run_scenario

SCENARIOS = sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*/scenario.yaml"))


@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=[p.parent.name for p in SCENARIOS])
def test_scenario(scenario_path: Path, tmp_path: Path):
    failures = run_scenario(scenario_path, tmp_path)
    if failures:
        pytest.fail(f"scenario {scenario_path.parent.name}:\n  " + "\n  ".join(failures),
                    pytrace=False)
