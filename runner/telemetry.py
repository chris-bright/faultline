import time
import threading
from runner.runtime import ContainerRuntime
from rich.console import Console


def run_probe_window(runtime: ContainerRuntime, container_name: str,
                     command: str, seconds: int) -> dict:
    """Run a probe command every second for `seconds` seconds, return aggregate stats."""
    samples = []
    end_time = time.time() + seconds
    while time.time() < end_time:
        tick_start = time.time()
        try:
            t0 = time.time()
            exit_code, _ = runtime.exec_run(container_name, command)
            latency_ms = (time.time() - t0) * 1000
            ok = exit_code == 0
        except Exception:
            latency_ms = None
            ok = False
        samples.append({"ok": ok, "latency_ms": latency_ms})
        elapsed = time.time() - tick_start
        sleep_for = 1.0 - elapsed
        if sleep_for > 0 and time.time() + sleep_for < end_time:
            time.sleep(sleep_for)

    total = len(samples)
    errors = sum(1 for s in samples if not s["ok"])
    latencies = sorted(s["latency_ms"] for s in samples if s["ok"] and s["latency_ms"] is not None)
    n = len(latencies)
    return {
        "total_samples": total,
        "error_rate": errors / total if total else 0,
        "avg_latency_ms": sum(latencies) / n if n else None,
        "p95_latency_ms": latencies[int(n * 0.95)] if n else None,
        "p99_latency_ms": latencies[min(int(n * 0.99), n - 1)] if n else None,
    }

console = Console()


class TelemetryCollector:
    """Polls the target during a scenario run and records health metrics."""

    def __init__(self, scenario_name: str, runtime: ContainerRuntime, container_name: str,
                 health_probe: str = None, health_path: str = None,
                 health_port: int = 8080, health_process: str = None):
        self.scenario_name = scenario_name
        self._runtime = runtime
        self._container_name = container_name

        if health_probe:
            self.health_probe = health_probe
        elif health_path:
            self.health_probe = f"curl -sf --max-time 1 -o /dev/null -w '%{{http_code}}' http://localhost:{health_port}{health_path} | grep -qE '^[1-4]'"
        elif health_process:
            self.health_probe = f"pid=$(pgrep -f '{health_process}' | head -1) && grep -qE 'State:.*[RS]' /proc/$pid/status"
        else:
            self.health_probe = f"nc -z localhost {health_port}"

        self._running = False
        self._thread = None
        self._samples = []
        self._fault_injected_at = None
        self._recovered_at = None

    def probe_once(self) -> bool:
        """Run the health probe once and return True if the container is healthy."""
        try:
            exit_code, _ = self._runtime.exec_run(self._container_name, self.health_probe)
            return exit_code == 0
        except Exception:
            return False

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

        latencies = sorted([s["latency_ms"] for s in self._samples if s["ok"] and s["latency_ms"] is not None])
        n_lat = len(latencies)
        avg_latency = sum(latencies) / n_lat if latencies else None
        p95 = latencies[int(n_lat * 0.95)] if latencies else None
        p99 = latencies[min(int(n_lat * 0.99), n_lat - 1)] if latencies else None

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
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "recovery_seconds": recovery_seconds,
            "fault_injected_at": self._fault_injected_at,
            "samples": self._samples,
        }

    def _poll(self):
        while self._running:
            ts = time.time()
            try:
                start = time.time()
                exit_code, _ = self._runtime.exec_run(self._container_name, self.health_probe)
                latency_ms = (time.time() - start) * 1000
                ok = exit_code == 0
            except Exception:
                latency_ms = None
                ok = False

            self._samples.append({"ts": ts, "ok": ok, "latency_ms": latency_ms})
            time.sleep(1)
