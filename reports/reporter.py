import json
import math
import tempfile
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich import box

console = Console()

RESULTS_DIR = Path(tempfile.gettempdir()) / "faultline"
MAX_RESULTS = 12
HISTOGRAM_WIDTH = 30


class Reporter:
    def __init__(self, debug: bool = False):
        self.debug = debug

    def render(self, results):
        if isinstance(results, dict):
            results = [results]

        payload = {
            "run_at": datetime.utcnow().isoformat() + "Z",
            "scenarios": results,
        }

        if self.debug:
            self._print_debug(payload)
        else:
            self._print_summary(results)

        self._save(payload)

    def _print_summary(self, results: list):
        console.print()
        console.rule("[bold]faultline results")
        for result in results:
            self._print_scenario(result)

    def _print_scenario(self, result: dict):
        metrics = result.get("metrics", {})
        samples = metrics.get("samples", [])
        latencies = [s["latency_ms"] for s in samples if s.get("ok") and s.get("latency_ms") is not None]

        if result.get("skipped"):
            console.print(f"\n[bold cyan]{result['scenario']}[/bold cyan]  "
                          f"[dim]{result['fault_type']}[/dim]  "
                          f"[yellow]SKIP[/yellow]")
            return

        console.print(f"\n[bold cyan]{result['scenario']}[/bold cyan]  "
                      f"[dim]{result['fault_type']}[/dim]")

        if not latencies:
            console.print("[dim]No latency data collected.[/dim]")
            return

        # Stats
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        avg = sum(latencies_sorted) / n
        p50 = latencies_sorted[int(n * 0.50)]
        p95 = latencies_sorted[int(n * 0.95)]
        p99 = latencies_sorted[min(int(n * 0.99), n - 1)]
        lo  = latencies_sorted[0]
        hi  = latencies_sorted[-1]

        stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        stats.add_column("stat", style="dim")
        stats.add_column("value")
        stats.add_row("samples",          str(metrics.get("total_samples", n)))
        stats.add_row("error_rate",       f"{metrics.get('error_rate', 0):.1%}")
        stats.add_row("recovery",         f"{metrics.get('recovery_seconds', '—'):.2f}s" if isinstance(metrics.get('recovery_seconds'), float) and metrics.get('recovery_seconds') != float('inf') else "—")
        stats.add_row("min latency",      f"{lo:.1f}ms")
        stats.add_row("avg latency",      f"{avg:.1f}ms")
        stats.add_row("p50",              f"{p50:.1f}ms")
        stats.add_row("p95",              f"{p95:.1f}ms")
        stats.add_row("p99",              f"{p99:.1f}ms")
        stats.add_row("max latency",      f"{hi:.1f}ms")
        console.print(stats)

        # Histogram
        self._print_histogram(latencies_sorted)

    def _print_histogram(self, latencies: list):
        lo = latencies[0]
        hi = latencies[-1]
        if hi == lo:
            hi = lo + 1

        NUM_BUCKETS = 10
        bucket_size = (hi - lo) / NUM_BUCKETS
        buckets = [0] * NUM_BUCKETS
        for v in latencies:
            idx = min(int((v - lo) / bucket_size), NUM_BUCKETS - 1)
            buckets[idx] += 1

        max_count = max(buckets) or 1
        console.print("[dim]latency distribution (ms)[/dim]")
        for i, count in enumerate(buckets):
            label_lo = lo + i * bucket_size
            label_hi = label_lo + bucket_size
            bar = "█" * math.ceil(count / max_count * HISTOGRAM_WIDTH)
            console.print(f"  [dim]{label_lo:6.0f}-{label_hi:<6.0f}[/dim]  [cyan]{bar:<{HISTOGRAM_WIDTH}}[/cyan]  {count}")

    def _print_debug(self, payload: dict):
        console.print()
        console.rule("[bold]faultline results (debug)")
        syntax = Syntax(json.dumps(payload, indent=2), "json", theme="monokai")
        console.print(syntax)

    def _save(self, payload: dict):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"run_{ts}.json"
        out_path.write_text(json.dumps(payload, indent=2))
        console.print(f"\n[dim]Results saved: {out_path}[/dim]")
        self._rotate()

    def _rotate(self):
        files = sorted(RESULTS_DIR.glob("run_*.json"))
        for old in files[:-MAX_RESULTS]:
            old.unlink()
