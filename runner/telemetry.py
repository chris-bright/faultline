import time
import threading
from rich.console import Console

console = Console()


class TelemetryCollector:
    """Polls the target during a scenario run and records health metrics."""

    def __init__(self, scenario_name: str, container):
        self.scenario_name = scenario_name
        self.container = container
        self._running = False
        self._thread = None
        self._samples = []
        self._fault_injected_at = None
        self._recovered_at = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def mark_fault(self):
        self._fault_injected_at = time.time()

    def mark_recovery(self):
        self._recovered_at = time.time()

    def collect(self) -> dict:
        if not self._samples:
            return {}

        total = len(self._samples)
        errors = sum(1 for s in self._samples if not s["ok"])
        error_rate = errors / total if total else 0

        latencies = [s["latency_ms"] for s in self._samples if s["ok"] and s["latency_ms"] is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None

        recovery_seconds = float("inf")
        if self._fault_injected_at:
            first_recovery = next(
                (s for s in self._samples if s["ok"] and s["ts"] > self._fault_injected_at),
                None,
            )
            if first_recovery:
                recovery_seconds = first_recovery["ts"] - self._fault_injected_at

        return {
            "total_samples": total,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency,
            "recovery_seconds": recovery_seconds,
            "samples": self._samples,
        }

    def _poll(self):
        while self._running:
            ts = time.time()
            try:
                start = time.time()
                exit_code, output = self.container.exec_run(
                    "curl -sf -o /dev/null -w '%{http_code}' http://localhost:8080/health",
                    demux=False,
                )
                latency_ms = (time.time() - start) * 1000
                status_code = int(output.decode().strip()) if output else 0
                ok = exit_code == 0 and status_code < 500
            except Exception:
                latency_ms = None
                ok = False

            self._samples.append({"ts": ts, "ok": ok, "latency_ms": latency_ms})
            time.sleep(1)
