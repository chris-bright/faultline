import os
import time
import requests
from rich.console import Console
from runner.result import ScenarioResult

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

    def submit(self, results: list[ScenarioResult]):
        ts = int(time.time())

        for result in results:
            tags = self._build_tags(result)
            self._submit_metrics(result, ts, tags)

        # Group by (run_id, scenario) — one pair of events per scenario run
        groups: dict[tuple, list[ScenarioResult]] = {}
        for result in results:
            key = (result.run_id or "", result.scenario)
            groups.setdefault(key, []).append(result)

        for group in groups.values():
            self._submit_scenario_events(group)

        mode_label = f"agent ({self.agent_host}:{self.agent_port})" if self.mode == "agent" else self.site
        console.print(f"[dim]Submitted to Datadog ({mode_label})[/dim]")

    def _build_tags(self, result: ScenarioResult) -> list[str]:
        tags = [
            f"scenario:{result.scenario}",
            f"domain:{result.domain or 'unknown'}",
            f"fault_type:{result.fault_type}",
            f"target:{result.target}",
            f"service:{result.service}",
            f"skipped:{'true' if result.skipped else 'false'}",
        ]
        if result.run_id:
            tags.append(f"run_id:{result.run_id}")
        for ct in result.compliance_tags:
            tags.append(f"compliance:{ct}")
        return tags

    def _submit_metrics(self, result: ScenarioResult, ts: int, tags: list[str]):
        metrics = result.metrics
        skipped = result.skipped
        probes = (metrics.get("probes", {}) or {}) if not skipped else {}

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
            for probe_name, windows in probes.items():
                for w in windows:
                    ptags = tags + [f"probe:{probe_name}", f"probe_window:{w.get('window', 'unknown')}"]
                    if w.get("error_rate") is not None:
                        self._statsd.gauge(f"{DD_METRIC_PREFIX}.probe.error_rate", w["error_rate"], tags=ptags)
                    if w.get("avg_latency_ms") is not None:
                        self._statsd.gauge(f"{DD_METRIC_PREFIX}.probe.avg_latency_ms", w["avg_latency_ms"], tags=ptags)
                    if w.get("p99_latency_ms") is not None:
                        self._statsd.gauge(f"{DD_METRIC_PREFIX}.probe.p99_latency_ms", w["p99_latency_ms"], tags=ptags)
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
        for probe_name, windows in probes.items():
            for w in windows:
                ptags = tags + [f"probe:{probe_name}", f"probe_window:{w.get('window', 'unknown')}"]
                if w.get("error_rate") is not None:
                    series.append(self._gauge("probe.error_rate", w["error_rate"], ts, ptags))
                if w.get("avg_latency_ms") is not None:
                    series.append(self._gauge("probe.avg_latency_ms", w["avg_latency_ms"], ts, ptags))
                if w.get("p99_latency_ms") is not None:
                    series.append(self._gauge("probe.p99_latency_ms", w["p99_latency_ms"], ts, ptags))

        url = DD_API_URL.format(site=self.site)
        resp = requests.post(url, headers=self._headers, json={"series": series}, timeout=10)
        if not resp.ok:
            console.print(f"[yellow]Warning: metrics submission failed ({resp.status_code}): {resp.text}[/yellow]")

    def _submit_scenario_events(self, group: list[ScenarioResult]):
        rep = group[0]
        all_skipped = all(r.skipped for r in group)
        if all_skipped:
            return

        targets = [r.target for r in group]
        compliance_str = ", ".join(rep.compliance_tags) if rep.compliance_tags else "none"
        steps_str = "\n".join(f"  {s}" for s in rep.step_summary) if rep.step_summary else f"  {rep.fault_type}"

        start_ts = int(rep.started_at) if rep.started_at else int(time.time())
        scenario_tags = [
            f"scenario:{rep.scenario}",
            f"domain:{rep.domain or 'unknown'}",
            f"fault_type:{rep.fault_type}",
        ]
        if rep.run_id:
            scenario_tags.append(f"run_id:{rep.run_id}")
        for ct in rep.compliance_tags:
            scenario_tags.append(f"compliance:{ct}")

        start_text = (
            f"%%% \n"
            f"**Scenario:** {rep.scenario}  \n"
            f"**Targets:** {', '.join(targets)}  \n"
            f"**Steps:**  \n{steps_str}  \n"
            f"**Compliance:** {compliance_str}  \n"
            f" %%%"
        )

        # Per-target results table
        rows = []
        completed_at = start_ts
        for r in group:
            if r.skipped:
                rows.append(f"| {r.target} | skipped | — | — | — |")
                continue
            m = r.metrics
            error_rate = f"{m['error_rate']:.1%}" if m.get("error_rate") is not None else "—"
            avg = f"{m['avg_latency_ms']:.0f}ms" if m.get("avg_latency_ms") is not None else "—"
            p99 = f"{m['p99_latency_ms']:.0f}ms" if m.get("p99_latency_ms") is not None else "—"
            rec = m.get("recovery_seconds")
            rec_str = f"{rec:.1f}s" if rec and rec != float("inf") else "—"
            rows.append(f"| {r.target} | {error_rate} | {avg} | {p99} | {rec_str} |")
            if m.get("fault_injected_at"):
                completed_at = max(completed_at, int(m["fault_injected_at"]) + 60)

        table = "\n".join(rows)
        execution_error = next((r.error for r in group if r.error), None)
        alert_type = "error" if execution_error else "success"

        # Probe breakdown across all targets
        probe_lines = []
        for r in group:
            if r.skipped:
                continue
            for probe_name, windows in (r.metrics.get("probes", {}) or {}).items():
                for w in windows:
                    label = w.get("window", "")
                    err = f"{w['error_rate']:.1%}" if w.get("error_rate") is not None else "—"
                    avg = f"{w['avg_latency_ms']:.0f}ms" if w.get("avg_latency_ms") is not None else "—"
                    p99 = f"{w['p99_latency_ms']:.0f}ms" if w.get("p99_latency_ms") is not None else "—"
                    probe_lines.append(f"| {r.target} | {probe_name} | {label} | {err} | {avg} | {p99} |")

        probe_section = ""
        if probe_lines:
            probe_table = "\n".join(probe_lines)
            probe_section = (
                f"\n**Workload Probes:**  \n"
                f"| Target | Probe | Window | Error Rate | Avg Latency | p99 Latency |  \n"
                f"|--------|-------|--------|-----------|-------------|-------------|  \n"
                f"{probe_table}  \n"
            )

        error_section = f"\n**Error:** {execution_error}  \n" if execution_error else ""

        complete_text = (
            f"%%% \n"
            f"| Target | Error Rate | Avg Latency | p99 Latency | Recovery |  \n"
            f"|--------|-----------|-------------|-------------|----------|  \n"
            f"{table}  \n"
            f"{probe_section}"
            f"{error_section}"
            f" %%%"
        )

        if self.mode == "agent":
            self._statsd.event(
                f"faultline: {rep.scenario} started",
                start_text,
                alert_type="info",
                tags=scenario_tags + ["faultline:start"],
                date_happened=start_ts,
            )
            self._statsd.event(
                f"faultline: {rep.scenario} complete",
                complete_text,
                alert_type=alert_type,
                tags=scenario_tags + ["faultline:complete"],
                date_happened=completed_at,
            )
            return

        url = DD_EVENTS_URL.format(site=self.site)
        for event in [
            {
                "title": f"faultline: {rep.scenario} started",
                "text": start_text,
                "date_happened": start_ts,
                "alert_type": "info",
                "tags": scenario_tags + ["faultline:start"],
            },
            {
                "title": f"faultline: {rep.scenario} complete",
                "text": complete_text,
                "date_happened": completed_at,
                "alert_type": alert_type,
                "tags": scenario_tags + ["faultline:complete"],
            },
        ]:
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
