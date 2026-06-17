# faultline

Fault injection agent for containerized services. Attaches to running containers via the Docker socket, injects controlled faults, collects telemetry, and ships results to Datadog as metrics and events.

> **Security note:** faultline runs with `--pid=host` and elevated Linux capabilities (`CAP_NET_ADMIN`, `CAP_SYS_PTRACE`, `CAP_SYS_ADMIN`) to inject faults at the host level without modifying target container images. Only run it in environments you control.

> **Airgap note:** faultline does not manage the network — if you want an isolated test environment, run your target in an internal Docker network yourself.

## Concept

```
target.yaml → attach to running container → fault injection → telemetry → JSON + Datadog metrics/events
```

No evaluation layer — faultline surfaces raw metrics only. Thresholds and alerting live in Datadog.

## Fault Domains

| Domain | Examples |
|---|---|
| Infrastructure | CPU stress, memory pressure, process freeze, packet loss, DNS blackhole, disk I/O, network jitter, IP blackhole |
| Code | Dependency killed, malformed input, latency injection |
| Cloud | Missing env vars, secret rotation simulation |
| Container | OOM kill, read-only filesystem, capability drop |
| Security | Privilege escalation, secret exfiltration, lateral movement, log injection, memory scraping |

The security domain is active testing — not misconfiguration scanning. Each scenario attempts an attack vector and measures whether the system detected or blocked it.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run a single scenario
python __main__.py run -c targets/simple_api/target.yaml -s scenarios/infrastructure/cpu_stress.yaml

# Run all scenarios in a domain
python __main__.py run -c targets/simple_api/target.yaml -d infrastructure

# Skip Datadog submission
python __main__.py run -c targets/simple_api/target.yaml -d infrastructure --no-submit

# Full sample data as JSON
python __main__.py run -c targets/simple_api/target.yaml -d infrastructure --debug
```

Results are saved to `results_dir` (default `/tmp/faultline/`, last 12 runs kept) and submitted to Datadog if configured.

## Configuration

faultline is configured via `faultline.yaml` in the working directory. CLI flags override config file values.

```yaml
datadog:
  submission_mode: agentless   # agent (DogStatsD → localhost) | agentless (direct HTTP)
  site: datadoghq.com          # datadoghq.com | datadoghq.eu | us3.datadoghq.com | etc.
  agent_host: localhost        # DogStatsD host (agent mode only)
  agent_port: 8125             # DogStatsD port (agent mode only)

output:
  debug: false                 # print full sample JSON after each scenario
  results_dir: /tmp/faultline  # where JSON result files are written
```

**Submission modes:**
- `agentless` — POSTs directly to the Datadog API. Requires `DD_API_KEY` env var and outbound connectivity to `*.datadoghq.com`.
- `agent` — sends via DogStatsD to a local Datadog Agent on `agent_host:agent_port`. No outbound connectivity required from faultline itself; the agent handles forwarding.

`DD_API_KEY` is always read from the environment — never put it in `faultline.yaml`.

## Target Config

Each target needs a `target.yaml` pointing at a running container:

```yaml
container: my-app       # name of the running Docker container
health_path: /health    # HTTP health endpoint (curl, 1s timeout)
port: 8080
process: python         # process name for /proc state check (fallback)
```

Health probe priority: `health_probe` (explicit shell command) → HTTP `health_path` → `/proc/<pid>/status` state → `nc -z port`

faultline runs a pre-flight health check before each scenario. If the container is already unhealthy the scenario aborts rather than producing misleading results.

Scenarios are skipped with a `SKIP` result if a required tool (`tc`, `stress-ng`, `iptables`) is not available in the target — no false passes.

## Reference Targets

```bash
docker compose up -d simple_api   # bring up one target
docker compose up -d              # bring up all targets
docker compose build keycloak     # rebuild a specific image
```

| Target | Port | Notes |
|---|---|---|
| `simple_api` | 8080 | Python Flask API, full tool set installed |
| `redis` | 6379 | Redis with stress/network tools added |
| `grafana` | 3000 | Grafana with stress/network tools added |
| `keycloak` | 8081 | Keycloak on ubi9-micro — no package manager, most fault types skip |

## Datadog Integration

Each scenario run submits:

**Metrics** (tagged `scenario`, `domain`, `fault_type`, `target`, `skipped`, `compliance`):
- `faultline.execution` — count, emitted for every run including skips
- `faultline.error_rate` — fraction of health probe failures during fault window
- `faultline.avg_latency_ms`, `faultline.p95_latency_ms`, `faultline.p99_latency_ms`
- `faultline.recovery_seconds` — time from fault injection to first successful probe
- `faultline.total_samples` — number of health probes taken

**Events** (appear as annotations on APM traces and dashboards):
- Fault inject event (`info`) — fired at injection time, includes compliance tags
- Recovery event (`success`) — fired at recovery time, includes error rate, avg/p99 latency

## Architecture

faultline is built in four layers:

**Container runtime abstraction** (`runner/runtime.py`) — a `ContainerRuntime` interface with a `DockerRuntime` implementation. All container operations (attach, exec, get PID, pause/unpause, kill) go through this interface, keeping the rest of the codebase containerizer-agnostic. `PodmanRuntime` and `KubernetesRuntime` stubs exist for future implementation.

**Fault injection** (`runner/fault.py`) — the `FaultInjector` uses `nsenter` to enter the target container's Linux namespaces from the host, injecting faults at the OS level without touching the target image. This means targets need no tools installed — `tc`, `stress-ng`, and `iptables` run in faultline's own container against the target's namespaces. Falls back to `docker exec` for scenarios that don't require host-level access. Raises `FaultNotApplied` if a required tool is missing, producing a clean `SKIP` result rather than a false pass.

**Telemetry** (`runner/telemetry.py`) — polls the target's health probe once per second throughout the scenario (baseline → fault → recovery). Captures probe latency, error rate, p95/p99, and time-to-recovery. The health probe is configurable per target: explicit shell command, HTTP path, process name, or TCP port check.

**Submission** (`reports/`) — `reporter.py` renders a stdout histogram and saves a JSON file. `datadog.py` submits metrics and events to Datadog via either DogStatsD (agent mode, no outbound required) or direct HTTP (agentless mode). Events are annotated on APM traces and dashboards at the exact fault injection and recovery timestamps.

The `orchestrator.py` ties these together: pre-flight check → baseline collection → fault injection → observation → recovery → telemetry harvest → report + submit.

## Project Structure

```
faultline/
├── faultline.yaml              # config (submission mode, DD site, output dir)
├── faultline.sh                # Docker launch script with required capabilities
├── scenarios/                  # YAML fault scenario definitions
│   ├── infrastructure/
│   ├── code/
│   ├── cloud/
│   ├── container/
│   └── security/
├── targets/                    # Reference targets (bring your own)
│   ├── simple_api/
│   ├── redis/
│   ├── grafana/
│   └── keycloak/
├── runner/
│   ├── runtime.py              # ContainerRuntime interface + DockerRuntime
│   ├── sandbox.py              # Attaches to a running container via the runtime
│   ├── fault.py                # Fault injection (nsenter host-level + exec fallback)
│   ├── telemetry.py            # Health polling during scenario runs
│   └── orchestrator.py         # Scenario execution
├── reports/
│   ├── reporter.py             # stdout histogram + JSON file output
│   └── datadog.py              # Datadog metrics and events submission
├── config.py                   # faultline.yaml loader
└── Dockerfile                  # faultline agent image (tc, iptables, stress-ng included)
```

## Requirements

- Docker running locally
- Python 3.11+

## Roadmap

**GitHub integration + scheduled runs** — link a GitHub repo and point faultline at a deployment Dockerfile or Terraform config. On each push (or on a schedule), faultline pulls the latest config, spins up the target, runs the fault suite, and ships results to Datadog. Gives you continuous resilience regression testing alongside your existing CI pipeline.

**Kubernetes support** — the `ContainerRuntime` interface is the right seam for this. Requires a DaemonSet deployment model: faultline agent pods run on every node with `hostPID: true`, exposing a local HTTP API that accepts fault commands and executes them via `nsenter`. A controller routes requests to the correct node agent after resolving which node the target pod lives on via the k8s API. `KubernetesRuntime` implements the interface by posting to the agent HTTP API instead of calling Docker SDK directly. The gaps vs Docker: no native pause/unpause (workaround: scale replicas to 0/1), and `get_pid()` requires the DaemonSet pod to be co-located with the target.

**Multi-component stack testing** — faultline currently assumes a single target container. Supporting a full service stack (API + queue + worker + DB) where faults can be injected at specific layers and cascade behaviour observed.

## Known Limitations

- **Network fault observability** — `tc netem` faults (packet loss, bandwidth cap, latency, jitter) are injected but health probes run via `docker exec` bypass the container's NIC, so probe latency won't reflect network degradation. Requires a sidecar HTTP prober making real requests through the network stack.
