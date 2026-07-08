from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class FaultParams:
    type: str
    params: dict = field(default_factory=dict)


@dataclass
class SingleFaultScenario:
    name: str
    fault: FaultParams
    domain: str = None
    description: str = ""
    baseline_seconds: int = 10
    observation_seconds: int = 30
    recovery_seconds: int = 15
    compliance_tags: list = field(default_factory=list)


def load_scenario(path: str) -> SingleFaultScenario:
    raw = yaml.safe_load(Path(path).read_text())
    _validate(raw, path)

    fault_raw = raw["fault"]
    fault_type = fault_raw.pop("type")
    fault = FaultParams(type=fault_type, params=fault_raw)

    return SingleFaultScenario(
        name=raw["name"],
        fault=fault,
        domain=raw.get("domain"),
        description=raw.get("description", ""),
        baseline_seconds=raw.get("baseline_seconds", 10),
        observation_seconds=raw.get("observation_seconds", 30),
        recovery_seconds=raw.get("recovery_seconds", 15),
        compliance_tags=raw.get("compliance_tags", []),
    )


def _validate(raw: dict, path: str):
    if "name" not in raw:
        raise ValueError(f"Scenario missing 'name': {path}")
    if "fault" not in raw:
        raise ValueError(f"Scenario missing 'fault': {path}")
    if "type" not in raw.get("fault", {}):
        raise ValueError(f"Scenario fault missing 'type': {path}")
