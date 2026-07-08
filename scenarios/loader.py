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


@dataclass
class ScenarioStep:
    action: str  # baseline | inject | wait | recover
    seconds: int = 0
    target: str = None   # required for inject and recover
    fault: FaultParams = None  # required for inject


@dataclass
class StepBasedScenario:
    name: str
    targets: list
    steps: list
    domain: str = None
    description: str = ""
    compliance_tags: list = field(default_factory=list)


def load_scenario(path: str) -> SingleFaultScenario | StepBasedScenario:
    raw = yaml.safe_load(Path(path).read_text())

    if "steps" in raw:
        return _load_step_based(raw, path)

    _validate_single(raw, path)

    fault_raw = dict(raw["fault"])
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


def _load_step_based(raw: dict, path: str) -> StepBasedScenario:
    if "name" not in raw:
        raise ValueError(f"Scenario missing 'name': {path}")
    if "targets" not in raw or not raw["targets"]:
        raise ValueError(f"Step-based scenario missing 'targets': {path}")

    steps = []
    for i, s in enumerate(raw["steps"]):
        action = s.get("action")
        if not action:
            raise ValueError(f"Step {i} missing 'action' in {path}")
        if action not in ("baseline", "inject", "wait", "recover"):
            raise ValueError(f"Step {i} unknown action '{action}' in {path}")

        fault = None
        if action == "inject":
            if "target" not in s:
                raise ValueError(f"Step {i} inject missing 'target' in {path}")
            if "fault" not in s:
                raise ValueError(f"Step {i} inject missing 'fault' in {path}")
            fault_raw = dict(s["fault"])
            fault_type = fault_raw.pop("type")
            fault = FaultParams(type=fault_type, params=fault_raw)

        if action == "recover" and "target" not in s:
            raise ValueError(f"Step {i} recover missing 'target' in {path}")

        steps.append(ScenarioStep(
            action=action,
            seconds=s.get("seconds", 0),
            target=s.get("target"),
            fault=fault,
        ))

    return StepBasedScenario(
        name=raw["name"],
        targets=raw["targets"],
        steps=steps,
        domain=raw.get("domain"),
        description=raw.get("description", ""),
        compliance_tags=raw.get("compliance_tags", []),
    )


def _validate_single(raw: dict, path: str):
    if "name" not in raw:
        raise ValueError(f"Scenario missing 'name': {path}")
    if "fault" not in raw:
        raise ValueError(f"Scenario missing 'fault': {path}")
    if "type" not in raw.get("fault", {}):
        raise ValueError(f"Scenario fault missing 'type': {path}")
