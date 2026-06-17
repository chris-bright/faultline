import os
import time
import requests
from rich.console import Console

console = Console()

DD_METRIC_PREFIX = "faultline"
DD_API_URL = "https://api.{site}/api/v2/series"
DD_EVENTS_URL = "https://api.{site}/api/v1/events"


class DatadogSubmitter:

    def __init__(self, mode: str = "agentless", api_key: str = None, site: str = None,
                 agent_host: str = "localhost", agent_port: int = 8125):
        self.mode = mode
        self.site = site or os.environ.get("DD_SITE", "datadoghq.com")
        self.agent_host = agent_host
        self.agent_port = agent_port

        if mode == "agentless":
            self.api_key = api_key or os.environ.get("DD_API_KEY")
            if not self.api_key:
                raise ValueError("DD_API_KEY not set — required for agentless submission")
            self._headers = {
                "DD-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }
        elif mode == "agent":
            self._init_statsd()
        else:
            raise ValueError(f"Unknown submission mode: {mode!r}. Use 'agent' or 'agentless'.")

    def _init_statsd(self):
        try:
            from datadog import initialize, statsd as _statsd
            initialize(statsd_host=self.agent_host, statsd_port=self.agent_port)
            self._statsd = _statsd
        except ImportError:
            raise RuntimeError("datadog package required for agent mode: pip install datadog")

    def submit(self, payload: dict):
        ts = int(time.time())

        for scenario in payload.get("scenarios", []):
            tags = self._build_tags(scenario)
            self._submit_metrics(scenario, ts, tags)
            if not scenario.get("skipped"):
                self._submit_events(scenario, tags)

        mode_label = f"agent ({self.agent_host}:{self.agent_port})" if self.mode == "agent" else self.site
        console.print(f"[dim]Submitted to Datadog ({mode_label})[/dim]")

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

        if self.mode == "agent":
            self._statsd.increment(f"{DD_METRIC_PREFIX}.execution", tags=tags)
            if not skipped and metrics:
                if metrics.get("error_rate") is not None:
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.error_rate", metrics["error_rate"], tags=tags)
                if metrics.get("avg_latency_ms") is not None:
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.avg_latency_ms", metrics["avg_latency_ms"], tags=tags)
                if metrics.get("p95_latency_ms") is not None:
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.p95_latency_ms", metrics["p95_latency_ms"], tags=tags)
                if metrics.get("p99_latency_ms") is not None:
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.p99_latency_ms", metrics["p99_latency_ms"], tags=tags)
                if metrics.get("total_samples") is not None:
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.total_samples", metrics["total_samples"], tags=tags)
                recovery = metrics.get("recovery_seconds")
                if recovery is not None and recovery != float("inf"):
                    self._statsd.gauge(f"{DD_METRIC_PREFIX}.recovery_seconds", recovery, tags=tags)
            return

        # agentless: batch HTTP POST
        series = [self._count("execution", 1, ts, tags)]

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

        if not fault_injected_at:
            return

        compliance = scenario.get("compliance_tags", [])
        compliance_str = ", ".join(compliance) if compliance else "none"

        inject_text = (
            f"Fault injection started. Observing service behaviour under {scenario['fault_type']}.\n"
            f"Compliance: {compliance_str}"
        )

        recovered = recovery_seconds and recovery_seconds != float("inf")
        error_rate = metrics.get("error_rate")
        p99 = metrics.get("p99_latency_ms")
        avg = metrics.get("avg_latency_ms")

        recovery_text_parts = [f"Service recovered in {recovery_seconds:.2f}s." if recovered else "Service did not recover within observation window."]
        if error_rate is not None:
            recovery_text_parts.append(f"Error rate during fault: {error_rate:.1%}")
        if avg is not None:
            recovery_text_parts.append(f"Avg latency: {avg:.1f}ms")
        if p99 is not None:
            recovery_text_parts.append(f"p99 latency: {p99:.1f}ms")
        recovery_text = "\n".join(recovery_text_parts)

        if self.mode == "agent":
            self._statsd.event(
                f"faultline: {scenario['fault_type']} injected into {scenario.get('target')}",
                inject_text,
                alert_type="info",
                tags=tags + ["faultline:inject"],
                date_happened=int(fault_injected_at),
            )
            if recovered:
                self._statsd.event(
                    f"faultline: {scenario['fault_type']} recovered on {scenario.get('target')}",
                    recovery_text,
                    alert_type="success",
                    tags=tags + ["faultline:recovery"],
                    date_happened=int(fault_injected_at + recovery_seconds),
                )
            return

        # agentless: individual HTTP POSTs
        events = [{
            "title": f"faultline: {scenario['fault_type']} injected into {scenario.get('target')}",
            "text": inject_text,
            "date_happened": int(fault_injected_at),
            "alert_type": "info",
            "tags": tags + ["faultline:inject"],
        }]

        if recovered:
            events.append({
                "title": f"faultline: {scenario['fault_type']} recovered on {scenario.get('target')}",
                "text": recovery_text,
                "date_happened": int(fault_injected_at + recovery_seconds),
                "alert_type": "success",
                "tags": tags + ["faultline:recovery"],
            })

        url = DD_EVENTS_URL.format(site=self.site)
        for event in events:
            resp = requests.post(url, headers=self._headers, json=event, timeout=10)
            if not resp.ok:
                console.print(f"[yellow]Warning: event submission failed ({resp.status_code}): {resp.text}[/yellow]")

    def _count(self, name: str, value: float, ts: int, tags: list[str]) -> dict:
        return {
            "metric": f"{DD_METRIC_PREFIX}.{name}",
            "type": 1,  # count
            "points": [{"timestamp": ts, "value": value}],
            "tags": tags,
        }

    def _gauge(self, name: str, value: float, ts: int, tags: list[str]) -> dict:
        return {
            "metric": f"{DD_METRIC_PREFIX}.{name}",
            "type": 3,  # gauge
            "points": [{"timestamp": ts, "value": value}],
            "tags": tags,
        }
