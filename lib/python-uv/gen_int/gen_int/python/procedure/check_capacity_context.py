# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import SpacePressureDetected
from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput, GetNodeUsageOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.environment import Disk
from gen_def.pydantic.telemetry import Progress


@dataclass
class check_capacity_emitters:
    space_pressure_detected: Callable[[SpacePressureDetected], None]


@dataclass
class check_capacity_queries:
    get_node_usage: Callable[[GetNodeUsageInput], GetNodeUsageOutput]


@dataclass
class check_capacity_env:
    store: Store
    disk: Disk


@dataclass
class check_capacity_telemetry:
    progress: Callable[[Progress], None]


@dataclass
class check_capacity_context:
    emit: check_capacity_emitters
    query: check_capacity_queries
    env: check_capacity_env
    telemetry: check_capacity_telemetry
