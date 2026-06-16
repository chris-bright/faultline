# faultline

Fault injection agent for containerized services. Attaches to running containers via the Docker socket, injects controlled faults, collects telemetry, and outputs structured results for analysis or downstream submission to Datadog.

> **Airgap note:** faultline does not manage the network — if you want an isolated test environment, run your target in an internal Docker network yourself. faultline works against whatever is running.

## Concept

```
target.yaml → attach to running container → fault injection → telemetry → JSON results + stdout histogram
```

## Fault Domains

| Domain | Examples |
|---|---|
| Infrastructure | CPU stress, memory pressure, process freeze, packet loss, DNS blackhole |
| Code | Dependency killed, malformed input, latency injection |
| Cloud | Missing env vars, secret rotation simulation |
| Container | OOM kill, read-only filesystem, capability drop |
| Security | Privilege escalation, secret exfiltration, lateral movement, log injection, memory scraping |

The security domain is active testing — not misconfiguration scanning. Each scenario attempts an attack vector and measures whether the system detected or blocked it.

## Usage

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run a single scenario against a running container
python __main__.py run --config targets/simple_api/target.yaml --scenario scenarios/infrastructure/cpu_stress.yaml

# Run all scenarios in a domain
python __main__.py run --config targets/simple_api/target.yaml --domain infrastructure

# Full sample data as JSON
python __main__.py run --config targets/simple_api/target.yaml --domain infrastructure --debug
```

Results are saved to `$TMPDIR/faultline/run_<timestamp>.json` (last 12 runs kept).

## Target Config

Each target needs a `target.yaml` pointing at a running container:

```yaml
container: my-app          # name of the running Docker container to attach to
health_path: /health       # HTTP path (uses curl with 1s timeout)
port: 8080
process: python            # process name for /proc state check (fallback)
```

Health probe priority: `health_probe` (explicit command) → HTTP `health_path` → `/proc/<pid>/status` state → `nc -z port`

faultline performs a pre-flight health check before each scenario. If the container is already unhealthy, the scenario is aborted rather than producing misleading results.

Scenarios are skipped with a clear `SKIP` result if a required tool (`tc`, `stress-ng`, `iptables`) is not available in the target container — no false PASSes.

## Project Structure

```
faultline/
├── scenarios/          # YAML fault scenario definitions
│   ├── infrastructure/
│   ├── code/
│   ├── cloud/
│   ├── container/
│   └── security/
├── targets/            # Example target configs (bring your own)
│   └── simple_api/
├── runner/
│   ├── runtime.py      # ContainerRuntime interface + DockerRuntime
│   ├── sandbox.py      # Attaches to a running container via the runtime
│   ├── fault.py        # Fault injection (nsenter host-level + exec fallback)
│   ├── telemetry.py    # Health polling during scenario runs
│   └── orchestrator.py # Scenario execution + scoring
├── reports/            # JSON output + stdout histogram renderer
├── Dockerfile          # faultline agent image (includes tc, iptables, stress-ng)
└── faultline.sh        # Launch script with required capabilities
```

## Requirements

- Docker running locally
- Python 3.11+

## Roadmap

**Privileged host-level injection** — the current model execs fault tools inside the target container, which means the target must have `tc`, `stress-ng`, and `iptables` installed. The correct architecture (how Gremlin does it) is to run faultline as a privileged container with host pid/network namespace access and inject faults from outside the target entirely — making it container-image-agnostic. The agent will be scoped to specific Linux capabilities (`CAP_NET_ADMIN`, `CAP_SYS_PTRACE`, `CAP_SYS_ADMIN`) rather than full `--privileged`, and will self-terminate after execution completes. A Datadog account key will be required to unlock the privileged run as an auth gate.

**GitHub integration + scheduled runs** — link a GitHub repo and point faultline at a deployment Dockerfile or Terraform config. On each push (or on a schedule), faultline pulls the latest config, spins up the target, runs the fault suite, and ships results to Datadog. Gives you continuous resilience regression testing alongside your existing CI pipeline.

**DD results submission** — the JSON output is already shaped for Datadog. The submission layer will POST fault injection events to the DD Events API (so they appear as annotations on APM traces and dashboards) and submit scenario metrics as custom metrics. Customers already tracing their services with DD APM will see exactly which spans and functions break during each fault window.

**Multi-component stack testing** — faultline currently assumes a single target container. Supporting a full service stack (API + queue + worker + DB) where faults can be injected at specific layers and cascade behavior observed. Requires stack definitions (similar to docker-compose), per-component health probes, and fault targeting by service name.

## Known Limitations

- **Network fault observability** — `tc netem` faults (packet loss, bandwidth cap, corruption) are injected but unobservable via `docker exec` health probes since the probe bypasses the container's network stack. Requires a sidecar prober making real HTTP requests through the network. Scenarios correctly SKIP on targets without `tc`.
- **Network faults require host-level injection** — tied to the privileged container roadmap item above.
