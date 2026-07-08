from dataclasses import dataclass, field, asdict


@dataclass
class ScenarioResult:
    scenario: str
    fault_type: str
    target: str
    service: str
    domain: str = None
    skipped: bool = False
    metrics: dict = field(default_factory=dict)
    compliance_tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("metrics", {}).get("recovery_seconds") == float("inf"):
            d["metrics"]["recovery_seconds"] = None
        return d
