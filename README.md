# faultline

Controlled fault injection and compliance evaluation for infrastructure, code, cloud config, and containers.

Spins up an isolated environment, runs a target through defined fault scenarios, collects telemetry via Datadog, and scores results against compliance frameworks (CIS, SOC 2, PCI-DSS).

## Concept

```
scenario.yaml → sandbox (airgapped Docker network) → target deployment
    → fault injection → telemetry collection → compliance evaluation → report
```

## Fault Domains

| Domain | Examples |
|---|---|
| Infrastructure | CPU stress, memory pressure, disk fill, network partition |
| Code | Dependency killed, malformed input, slow dependency (latency injection) |
| Cloud | Missing env vars, secret rotation simulation |
| Container | OOM kill, read-only filesystem, capability drop |
| Security | Privilege escalation attempts, secret exfiltration, lateral movement, log injection, memory scraping |

The security domain is active testing — not misconfiguration scanning (Datadog CSM already does that).
Each scenario attempts an attack vector in the isolated environment and scores whether the system
detected or blocked it, not just whether the config was correct.

## Compliance Frameworks (POC)

- CIS Docker Benchmark
- SOC 2 (CC6 — Logical Access, CC7 — System Operations)
- PCI-DSS 10.x (logging & monitoring controls)
- OWASP Docker Top 10

## Project Structure

```
faultline/
├── scenarios/          # YAML fault scenario definitions
│   ├── infrastructure/
│   ├── code/
│   ├── cloud/
│   ├── container/
│   └── security/
├── targets/            # Pre-baked target services to test against
│   └── simple_api/     # Flask API — default POC target
├── runner/             # Orchestrates sandbox lifecycle + fault execution
├── evaluator/          # Scores telemetry + maps findings to compliance controls
└── reports/            # Output — JSON + human-readable audit summaries
```

## Quickstart

```bash
pip install -r requirements.txt

# Run a single scenario
python -m faultline run --scenario scenarios/infrastructure/cpu_stress.yaml --target simple_api

# Run all scenarios in a domain with a compliance report
python -m faultline run --domain infrastructure --target simple_api --report

# Run security domain against OWASP Docker Top 10 and SOC 2
python -m faultline run --domain security --target simple_api --report --framework owasp-docker --framework soc2
```

## Requirements

- Docker (with compose)
- Python 3.11+
- Datadog Agent running locally (or DD_API_KEY set for direct submission)
