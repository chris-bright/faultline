# faultline

Controlled fault injection for containerized services. Spins up an airgapped Docker sandbox, runs a target through defined fault scenarios, collects telemetry, and outputs structured results for analysis or downstream submission to Datadog.

## Concept

```
scenario.yaml → sandbox (airgapped Docker network) → target deployment
    → fault injection → telemetry collection → JSON results + stdout histogram
```

## Fault Domains

| Domain | Examples |
|---|---|
| Infrastructure | CPU stress, memory pressure, disk fill, network stress, process freeze |
| Code | Dependency killed, malformed input, latency injection |
| Cloud | Missing env vars, secret rotation simulation |
| Container | OOM kill, read-only filesystem, capability drop |
| Security | Privilege escalation, secret exfiltration, lateral movement, log injection, memory scraping |

The security domain is active testing — not misconfiguration scanning.
Each scenario attempts an attack vector in the isolated environment and measures whether the system
detected or blocked it.

## Targets

Targets live in `targets/<name>/` and require:
- A `Dockerfile` (with `stress-ng`, `curl`, `procps` installed)
- A `target.yaml` describing how to health-check the service

```yaml
# target.yaml options
health_probe: "redis-cli PING | grep -q PONG"  # explicit probe command (highest priority)
health_path: /health                             # HTTP path (uses curl with 1s timeout)
port: 8080                                       # port for HTTP or fallback nc check
process: python                                  # process name for /proc state check
mem_limit: 256m
```

Health probe priority: `health_probe` → HTTP `health_path` → `/proc/<pid>/status` state → `nc -z port`

Built-in targets: `simple_api` (Flask), `grafana`, `redis`

## Project Structure

```
faultline/
├── scenarios/          # YAML fault scenario definitions
│   ├── infrastructure/
│   ├── code/
│   ├── cloud/
│   ├── container/
│   └── security/
├── targets/            # Target service definitions
│   ├── simple_api/     # Flask API — default POC target
│   ├── grafana/        # Grafana (Alpine-based)
│   └── redis/          # Redis (Alpine-based)
├── runner/             # Sandbox lifecycle, fault injection, telemetry
├── evaluator/          # Compliance control mapping (CIS, SOC 2, PCI-DSS)
└── reports/            # JSON output + stdout histogram renderer
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run a single scenario
python __main__.py run --scenario scenarios/infrastructure/cpu_stress.yaml --target simple_api

# Run all scenarios in a domain
python __main__.py run --domain infrastructure --target simple_api

# Run against a different target
python __main__.py run --domain infrastructure --target redis

# Full sample data output
python __main__.py run --scenario scenarios/infrastructure/cpu_stress.yaml --target simple_api --debug

# Verify target starts correctly before running faults
python __main__.py scaffold --target simple_api
```

Results are saved to `/tmp/faultline/run_<timestamp>.json` (last 12 runs kept).

## Requirements

- Docker running locally
- Python 3.11+
- `DD_API_KEY` set (used by the runner; not required for local-only runs)

## Future Direction

**Multi-component stack testing** — faultline currently assumes a single target container. The next major architectural step is supporting a full service stack (API + queue + worker + DB) where faults can be injected at specific layers and cascade behavior can be observed. E.g. kill the message queue and measure whether the API degrades gracefully and whether jobs are lost or retried. This requires stack definitions (similar to docker-compose), per-component health probes, and fault targeting by service name. A two-service spike (API + Redis) is the natural starting point before full multi-component support.

## Known Limitations / Backlog

- **Pre-built image support** — targets must currently be a local `Dockerfile`. A `--image` flag to pull from a registry is planned (`sandbox.py: _build_target_image`).
- **Custom endpoints** — `target.yaml` will support named API calls with sample payloads to measure real workload impact during fault windows, not just health probe status. This also unblocks network fault scenarios (packet loss, bandwidth cap, packet corruption) — the current `docker exec` health probe bypasses the container's network stack entirely, so `tc netem` faults have no observable effect. A sidecar prober container on the same isolated network making real requests to the target would go through eth0 and make network faults measurable without breaking the airgap.
- **Scoped seccomp for process freeze** — `process_freeze` currently uses `docker pause` (cgroups freezer) which freezes the whole container. A targeted seccomp profile allowing only `kill`/`ptrace` capabilities would enable single-process freeze without elevated privileges, matching how tools like Gremlin implement it.
