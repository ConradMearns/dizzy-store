"""The scenario suite, run against the REAL transport.

Every scenario in scenarios/ also runs with each device serving the real peer API
over real HTTP on localhost (dizzy_store.http_sim.HttpCluster) — same procedures,
projections, queries and policies, same assertions, same invariants; only the
wire differs from the in-process simulation. A scenario that passes in simulation
but fails here has found a gap between the two.
"""
from pathlib import Path

import pytest

from dizzy_store.http_sim import HttpCluster
from dizzy_store.scenario import run_scenario

SCENARIOS = sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*/scenario.yaml"))


@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=[p.parent.name for p in SCENARIOS])
def test_scenario_over_http(scenario_path: Path, tmp_path: Path):
    failures = run_scenario(scenario_path, tmp_path, cluster_factory=HttpCluster)
    if failures:
        pytest.fail(f"scenario {scenario_path.parent.name} (over HTTP):\n  "
                    + "\n  ".join(failures), pytrace=False)
