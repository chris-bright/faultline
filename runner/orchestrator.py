import time
import yaml
from pathlib import Path
from rich.console import Console
from runner.sandbox import Sandbox
from runner.fault import FaultInjector, FaultNotApplied
from runner.telemetry import TelemetryCollector

console = Console()


class Orchestrator:
    def __init__(self, config: str):
        config_path = Path(config)
        if not config_path.exists():
            raise FileNotFoundError(f"Target config not found: {config_path}")
        self.target_config = yaml.safe_load(config_path.read_text())
        self.container_name = self.target_config.get("container")
        if not self.container_name:
            raise ValueError(f"target.yaml must specify 'container' — the name of the running container to attach to")
        self.health_probe = self.target_config.get("health_probe")
        self.health_path = self.target_config.get("health_path")
        self.health_port = self.target_config.get("port", 8080)
        self.health_process = self.target_config.get("process")

    def run_scenario(self, scenario_path: str) -> dict:
        with open(scenario_path) as f:
            scenario = yaml.safe_load(f)
        return self._execute(scenario)

    def run_domain(self, domain: str) -> list[dict]:
        domain_path = Path(__file__).parent.parent / "scenarios" / domain
        results = []
        for scenario_file in sorted(domain_path.glob("*.yaml")):
            console.rule(f"[bold]{scenario_file.stem}")
            with open(scenario_file) as f:
                scenario = yaml.safe_load(f)
            results.append(self._execute(scenario))
        return results

    def _execute(self, scenario: dict) -> dict:
        console.print(f"\n[bold cyan]Scenario:[/bold cyan] {scenario['name']}")
        console.print(f"[dim]{scenario.get('description', '')}[/dim]\n")

        sandbox = Sandbox(self.container_name)
        sandbox.attach()

        telemetry = TelemetryCollector(
            scenario["name"],
            sandbox.runtime,
            sandbox.container_name,
            health_probe=self.health_probe,
            health_path=self.health_path,
            health_port=self.health_port,
            health_process=self.health_process,
        )

        console.print("[dim]Pre-flight: checking target health...[/dim]")
        if not telemetry.probe_once():
            raise RuntimeError(
                f"Pre-flight failed: container '{self.container_name}' is not healthy before fault injection. "
                "Fix the target before running scenarios."
            )
        console.print("[dim]Pre-flight: OK[/dim]")

        try:
            telemetry.start()

            console.print("[yellow]Collecting baseline...[/yellow]")
            time.sleep(scenario.get("baseline_seconds", 10))

            injector = FaultInjector(sandbox)
            console.print(f"[red]Injecting fault:[/red] {scenario['fault']['type']}")
            try:
                injector.inject(scenario["fault"])
            except FaultNotApplied as e:
                telemetry.stop()
                console.print(f"[bold red]SKIP:[/bold red] {e}")
                return {
                    "scenario": scenario["name"],
                    "domain": scenario.get("domain"),
                    "fault_type": scenario["fault"]["type"],
                    "passed": False,
                    "skipped": True,
                    "findings": [{"check": "fault_applied", "passed": False, "note": str(e)}],
                    "metrics": {},
                    "compliance_tags": scenario.get("compliance_tags", []),
                }
            telemetry.mark_fault()

            observation = scenario.get("observation_seconds", 30)
            console.print(f"[yellow]Observing for {observation}s...[/yellow]")
            time.sleep(observation)

            injector.recover(scenario["fault"])
            console.print("[yellow]Checking recovery...[/yellow]")
            time.sleep(scenario.get("recovery_seconds", 15))

            metrics = telemetry.collect()
            result = self._score(scenario, metrics)

        finally:
            telemetry.stop()

        console.print(f"[bold]Result:[/bold] {'[green]PASS' if result['passed'] else '[red]FAIL'}[/]")
        return result

    def _score(self, scenario: dict, metrics: dict) -> dict:
        expectations = scenario.get("expect", {})
        passed = True
        findings = []

        if "max_recovery_seconds" in expectations:
            actual = metrics.get("recovery_seconds", float("inf"))
            ok = actual <= expectations["max_recovery_seconds"]
            if not ok:
                passed = False
                findings.append({
                    "check": "recovery_time",
                    "expected": f"<= {expectations['max_recovery_seconds']}s",
                    "actual": f"{actual:.1f}s",
                    "passed": False,
                })

        if "error_rate_below" in expectations:
            actual = metrics.get("error_rate", 1.0)
            ok = actual <= expectations["error_rate_below"]
            if not ok:
                passed = False
                findings.append({
                    "check": "error_rate",
                    "expected": f"<= {expectations['error_rate_below']}",
                    "actual": f"{actual:.2%}",
                    "passed": False,
                })

        for bool_check in ("escalation_succeeded", "lateral_access_gained",
                           "secrets_exposed", "credentials_found_in_memory"):
            if bool_check in expectations:
                expected_val = expectations[bool_check]
                actual_val = metrics.get(bool_check, False)
                ok = actual_val == expected_val
                if not ok:
                    passed = False
                    findings.append({
                        "check": bool_check,
                        "expected": expected_val,
                        "actual": actual_val,
                        "passed": False,
                    })

        if expectations.get("detection_logged"):
            detected = metrics.get("detection_logged", False)
            if not detected:
                passed = False
                findings.append({
                    "check": "detection_logged",
                    "expected": True,
                    "actual": False,
                    "passed": False,
                    "note": "No detection signal observed during attack window",
                })

        return {
            "scenario": scenario["name"],
            "domain": scenario.get("domain"),
            "fault_type": scenario["fault"]["type"],
            "passed": passed,
            "findings": findings,
            "metrics": metrics,
            "compliance_tags": scenario.get("compliance_tags", []),
        }
