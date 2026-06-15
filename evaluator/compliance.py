from pathlib import Path
import yaml

# Maps compliance tags (used in scenario YAML) to control descriptions per framework
CONTROL_MAP = {
    "cis-docker": {
        "container.readonly_rootfs": {
            "control": "CIS Docker 5.12",
            "description": "Ensure the container's root filesystem is mounted as read only",
            "severity": "medium",
        },
        "container.no_privileged": {
            "control": "CIS Docker 5.4",
            "description": "Ensure privileged containers are not used",
            "severity": "high",
        },
        "container.memory_limit": {
            "control": "CIS Docker 5.10",
            "description": "Ensure memory usage for container is limited",
            "severity": "medium",
        },
        "container.network_isolation": {
            "control": "CIS Docker 5.29",
            "description": "Ensure Docker's default bridge network is not used",
            "severity": "low",
        },
        "infra.resource_exhaustion": {
            "control": "CIS Docker 5.10 / 5.11",
            "description": "Ensure CPU and memory limits are set to prevent resource exhaustion",
            "severity": "high",
        },
    },
    "soc2": {
        "infra.availability": {
            "control": "SOC 2 A1.2",
            "description": "System availability — service recovers within defined RTO",
            "severity": "high",
        },
        "code.dependency_resilience": {
            "control": "SOC 2 CC7.1",
            "description": "System monitoring — service degrades gracefully when dependencies fail",
            "severity": "medium",
        },
        "cloud.secret_management": {
            "control": "SOC 2 CC6.1",
            "description": "Logical access — secrets and credentials are managed securely",
            "severity": "high",
        },
        "infra.resource_exhaustion": {
            "control": "SOC 2 A1.1",
            "description": "Capacity planning — service handles resource pressure without data loss",
            "severity": "high",
        },
    },
    "owasp-docker": {
        "security.least_privilege": {
            "control": "OWASP Docker Top 10 D3",
            "description": "Network segmentation and least privilege — container cannot escalate to root",
            "severity": "critical",
        },
        "security.secret_hygiene": {
            "control": "OWASP Docker Top 10 D6",
            "description": "Protect secrets — credentials must not be readable from process memory or env",
            "severity": "critical",
        },
        "security.network_segmentation": {
            "control": "OWASP Docker Top 10 D4",
            "description": "Network segmentation — container cannot reach unintended hosts",
            "severity": "high",
        },
        "security.log_integrity": {
            "control": "OWASP Docker Top 10 D9",
            "description": "Container logging and monitoring — injected log patterns must be detected",
            "severity": "medium",
        },
    },
    "pci-dss": {
        "cloud.secret_management": {
            "control": "PCI-DSS 8.6",
            "description": "System/application accounts — credentials not hardcoded or exposed",
            "severity": "critical",
        },
        "infra.availability": {
            "control": "PCI-DSS 12.3.3",
            "description": "Business continuity — services recover per defined RTO/RPO",
            "severity": "high",
        },
        "container.network_isolation": {
            "control": "PCI-DSS 1.3",
            "description": "Network segmentation — containers are network-isolated",
            "severity": "critical",
        },
    },
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class ComplianceEvaluator:
    def __init__(self, frameworks: list[str]):
        self.frameworks = frameworks

    def evaluate(self, results) -> dict:
        if isinstance(results, dict):
            results = [results]

        violations = []
        passed_controls = []

        for result in results:
            tags = result.get("compliance_tags", [])
            scenario_passed = result.get("passed", True)

            for tag in tags:
                for framework in self.frameworks:
                    controls = CONTROL_MAP.get(framework, {})
                    if tag in controls:
                        control = controls[tag].copy()
                        control["framework"] = framework
                        control["tag"] = tag
                        control["scenario"] = result["scenario"]

                        if not scenario_passed:
                            control["status"] = "FAIL"
                            control["findings"] = result.get("findings", [])
                            violations.append(control)
                        else:
                            control["status"] = "PASS"
                            passed_controls.append(control)

        violations.sort(key=lambda v: SEVERITY_ORDER.get(v["severity"], 99))

        return {
            "frameworks": self.frameworks,
            "total_scenarios": len(results),
            "violations": violations,
            "passed_controls": passed_controls,
            "summary": {
                "critical": sum(1 for v in violations if v["severity"] == "critical"),
                "high": sum(1 for v in violations if v["severity"] == "high"),
                "medium": sum(1 for v in violations if v["severity"] == "medium"),
                "low": sum(1 for v in violations if v["severity"] == "low"),
            },
        }
