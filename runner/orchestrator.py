import os
import time
import yaml
import docker
from pathlib import Path
from rich.console import Console
from runner.sandbox import Sandbox
from runner.fault import FaultInjector
from runner.telemetry import TelemetryCollector

console = Console()


class Orchestrator:
    def __init__(self, target: str):
        self.target = target
        self.target_path = Path(__file__).parent.parent / "targets" / target
        self.docker = docker.from_env()

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

    def scaffold_only(self):
        sandbox = Sandbox(self.target_path, self.docker)
        sandbox.up()
        console.print(f"[green]Target '{self.target}' is up.[/green] Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sandbox.down()

    def _execute(self, scenario: dict) -> dict:
        console.print(f"\n[bold cyan]Scenario:[/bold cyan] {scenario['name']}")
        console.print(f"[dim]{scenario.get('description', '')}[/dim]\n")

        sandbox = Sandbox(self.target_path, self.docker)
        sandbox.up()
        telemetry = TelemetryCollector(scenario["name"], sandbox.get_container("target"))

        try:
            telemetry.start()

            # Baseline window
            console.print("[yellow]Collecting baseline...[/yellow]")
            time.sleep(scenario.get("baseline_seconds", 10))

            # Inject fault
            injector = FaultInjector(sandbox, self.docker)
            console.print(f"[red]Injecting fault:[/red] {scenario['fault']['type']}")
            injector.inject(scenario["fault"])
            telemetry.mark_fault()

            # Observation window
            observation = scenario.get("observation_seconds", 30)
            console.print(f"[yellow]Observing for {observation}s...[/yellow]")
            time.sleep(observation)

            # Recovery check
            injector.recover(scenario["fault"])
            console.print("[yellow]Checking recovery...[/yellow]")
            time.sleep(scenario.get("recovery_seconds", 15))

            metrics = telemetry.collect()
            console.print(f"[dim]samples={metrics.get('total_samples')} error_rate={metrics.get('error_rate')} recovery_seconds={metrics.get('recovery_seconds')}[/dim]")
            result = self._score(scenario, metrics)

        finally:
            telemetry.stop()
            sandbox.down()

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

        # Security-specific expectations
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
                    "note": "No detection signal observed in DD Agent or syslog during attack window",
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
