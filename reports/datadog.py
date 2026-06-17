import os
import time
import requests
from rich.console import Console

console = Console()

DD_METRIC_PREFIX = "faultline"
DD_API_URL = "https://api.{site}/api/v2/series"
DD_EVENTS_URL = "https://api.{site}/api/v1/events"


class DatadogSubmitter:

    def __init__(self, api_key: str = None, site: str = None):
        self.api_key = api_key or os.environ.get("DD_API_KEY")
        self.site = site or os.environ.get("DD_SITE", "datadoghq.com")
        if not self.api_key:
            raise ValueError("DD_API_KEY not set — cannot submit to Datadog")
        self._headers = {
            "DD-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    def submit(self, payload: dict):
        run_at = payload.get("run_at")
        ts = int(time.time())

        for scenario in payload.get("scenarios", []):
            tags = self._build_tags(scenario)
            self._submit_metrics(scenario, ts, tags)
            if not scenario.get("skipped"):
                self._submit_events(scenario, tags)

        console.print(f"[dim]Submitted to Datadog ({self.site})[/dim]")

    def _build_tags(self, scenario: dict) -> list[str]:
        tags = [
            f"scenario:{scenario['scenario']}",
            f"domain:{scenario.get('domain', 'unknown')}",
            f"fault_type:{scenario['fault_type']}",
            f"target:{scenario.get('target', 'unknown')}",
            f"skipped:{'true' if scenario.get('skipped') else 'false'}",
        ]
        for ct in scenario.get("compliance_tags", []):
            tags.append(f"compliance:{ct}")
        return tags

    def _submit_metrics(self, scenario: dict, ts: int, tags: list[str]):
        metrics = scenario.get("metrics", {})
        skipped = scenario.get("skipped", False)

        series = [
            self._gauge("skipped", 1 if skipped else 0, ts, tags),
        ]

        if not skipped and metrics:
            if metrics.get("error_rate") is not None:
                series.append(self._gauge("error_rate", metrics["error_rate"], ts, tags))
            if metrics.get("avg_latency_ms") is not None:
                series.append(self._gauge("avg_latency_ms", metrics["avg_latency_ms"], ts, tags))
            if metrics.get("p95_latency_ms") is not None:
                series.append(self._gauge("p95_latency_ms", metrics["p95_latency_ms"], ts, tags))
            if metrics.get("p99_latency_ms") is not None:
                series.append(self._gauge("p99_latency_ms", metrics["p99_latency_ms"], ts, tags))
            if metrics.get("total_samples") is not None:
                series.append(self._gauge("total_samples", metrics["total_samples"], ts, tags))
            recovery = metrics.get("recovery_seconds")
            if recovery is not None and recovery != float("inf"):
                series.append(self._gauge("recovery_seconds", recovery, ts, tags))

        url = DD_API_URL.format(site=self.site)
        resp = requests.post(url, headers=self._headers, json={"series": series}, timeout=10)
        if not resp.ok:
            console.print(f"[yellow]Warning: metrics submission failed ({resp.status_code}): {resp.text}[/yellow]")

    def _submit_events(self, scenario: dict, tags: list[str]):
        metrics = scenario.get("metrics", {})
        fault_injected_at = metrics.get("fault_injected_at")
        recovery_seconds = metrics.get("recovery_seconds")

        events = []

        if fault_injected_at:
            events.append({
                "title": f"faultline: {scenario['fault_type']} injected into {scenario.get('target')}",
                "text": (
                    f"Scenario: {scenario['scenario']}\n"
                    f"Domain: {scenario.get('domain')}\n"
                    f"Fault: {scenario['fault_type']}\n"
                    f"Target: {scenario.get('target')}"
                ),
                "date_happened": int(fault_injected_at),
                "alert_type": "warning",
                "tags": tags + ["faultline:inject"],
            })

            if recovery_seconds and recovery_seconds != float("inf"):
                events.append({
                    "title": f"faultline: {scenario['fault_type']} recovered on {scenario.get('target')}",
                    "text": f"Recovery time: {recovery_seconds:.2f}s",
                    "date_happened": int(fault_injected_at + recovery_seconds),
                    "alert_type": "success",
                    "tags": tags + ["faultline:recovery"],
                })

        url = DD_EVENTS_URL.format(site=self.site)
        for event in events:
            resp = requests.post(url, headers=self._headers, json=event, timeout=10)
            if not resp.ok:
                console.print(f"[yellow]Warning: event submission failed ({resp.status_code}): {resp.text}[/yellow]")

    def _gauge(self, name: str, value: float, ts: int, tags: list[str]) -> dict:
        return {
            "metric": f"{DD_METRIC_PREFIX}.{name}",
            "type": 3,  # gauge
            "points": [{"timestamp": ts, "value": value}],
            "tags": tags,
        }
