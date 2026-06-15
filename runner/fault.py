import docker
from rich.console import Console

console = Console()


class FaultInjector:
    """Injects faults into sandbox containers by fault type."""

    def __init__(self, sandbox, client: docker.DockerClient):
        self.sandbox = sandbox
        self.client = client

    def inject(self, fault: dict) -> bool:
        fault_type = fault["type"]
        handler = getattr(self, f"_inject_{fault_type}", None)
        if not handler:
            raise ValueError(f"Unknown fault type: {fault_type}")
        exit_code = handler(fault)
        if exit_code and exit_code != 0:
            console.print(f"[bold yellow]Warning: fault injection returned exit code {exit_code} — fault may not have applied[/bold yellow]")
            return False
        return True

    def recover(self, fault: dict):
        fault_type = fault["type"]
        handler = getattr(self, f"_recover_{fault_type}", None)
        if handler:
            handler(fault)

    # --- Infrastructure ---

    def _inject_cpu_stress(self, fault: dict):
        cores = fault.get("cores", 1)
        duration = fault.get("duration_seconds", 30)
        return self._exec_target(f"cd /tmp && stress-ng --cpu {cores} --timeout {duration}s &")

    def _recover_cpu_stress(self, fault: dict):
        self._exec_target("pkill stress-ng || true")

    def _inject_memory_pressure(self, fault: dict):
        mb = fault.get("mb", 128)
        return self._exec_target(f"cd /tmp && stress-ng --vm 1 --vm-bytes {mb}M --timeout 60s &")

    def _recover_memory_pressure(self, fault: dict):
        self._exec_target("pkill stress-ng || true")

    def _inject_process_freeze(self, fault: dict):
        container = self.sandbox.get_container("target")
        container.pause()
        console.print("[dim]Container paused via cgroups freezer[/dim]")

    def _recover_process_freeze(self, fault: dict):
        container = self.sandbox.get_container("target")
        try:
            container.unpause()
        except Exception:
            pass

    def _inject_disk_fill(self, fault: dict):
        mb = fault.get("mb", 100)
        self._exec_target(f"dd if=/dev/zero of=/tmp/faultline_fill bs=1M count={mb} &")

    def _recover_disk_fill(self, fault: dict):
        self._exec_target("rm -f /tmp/faultline_fill")

    def _inject_network_partition(self, fault: dict):
        # Drop all traffic except to DD agent
        container = self.sandbox.get_container("target")
        container.exec_run("iptables -I OUTPUT -j DROP", privileged=True)

    def _recover_network_partition(self, fault: dict):
        container = self.sandbox.get_container("target")
        container.exec_run("iptables -F OUTPUT", privileged=True)

    # --- Code ---

    def _inject_dependency_killed(self, fault: dict):
        dep = fault.get("service", "ddagent")
        container = self.sandbox.get_container(dep)
        if container:
            container.pause()
            console.print(f"[dim]Paused dependency: {dep}[/dim]")

    def _recover_dependency_killed(self, fault: dict):
        dep = fault.get("service", "ddagent")
        container = self.sandbox.get_container(dep)
        if container:
            container.unpause()

    def _inject_latency_injection(self, fault: dict):
        ms = fault.get("ms", 500)
        self._exec_target(
            f"tc qdisc add dev eth0 root netem delay {ms}ms",
            privileged=True,
        )

    def _recover_latency_injection(self, fault: dict):
        self._exec_target("tc qdisc del dev eth0 root || true", privileged=True)

    # --- Container ---

    def _inject_oom_kill(self, fault: dict):
        # Force OOM by allocating more memory than the container limit
        self._exec_target("stress-ng --vm 1 --vm-bytes 512M --timeout 10s &")

    def _recover_oom_kill(self, fault: dict):
        # Container restart is the recovery signal — sandbox handles restart detection
        pass

    def _inject_readonly_filesystem(self, fault: dict):
        self._exec_target("mount -o remount,ro /", privileged=True)

    def _recover_readonly_filesystem(self, fault: dict):
        self._exec_target("mount -o remount,rw / || true", privileged=True)

    # --- Cloud ---

    def _inject_missing_env(self, fault: dict):
        var = fault.get("var", "DATABASE_URL")
        self._exec_target(f"unset {var}")
        console.print(f"[dim]Unset env var: {var}[/dim]")

    def _recover_missing_env(self, fault: dict):
        pass  # env unset doesn't restore — target must handle absence gracefully

    def _inject_secret_rotation(self, fault: dict):
        var = fault.get("var", "API_KEY")
        self._exec_target(f"export {var}=ROTATED_INVALID_VALUE_XYZ")

    def _recover_secret_rotation(self, fault: dict):
        original = fault.get("original_value", "")
        var = fault.get("var", "API_KEY")
        if original:
            self._exec_target(f"export {var}={original}")

    # --- Security ---

    def _inject_privilege_escalation(self, fault: dict):
        # Attempt sudo, SUID binary abuse, and capability probing
        # Each attempt is recorded; success means the control failed
        checks = [
            "sudo id 2>&1 || true",
            "find / -perm -4000 -type f 2>/dev/null | head -5 || true",
            "cat /proc/1/status 2>&1 | grep -i cap || true",
            "id",
        ]
        for cmd in checks:
            self._exec_target(cmd)

    def _recover_privilege_escalation(self, fault: dict):
        pass  # no state to restore — attempts are read-only probes

    def _inject_secret_exfiltration(self, fault: dict):
        methods = fault.get("methods", [])
        if "proc_environ" in methods:
            self._exec_target("cat /proc/1/environ 2>/dev/null | tr '\\0' '\\n' | grep -iE 'key|secret|pass|token' || true")
        if "env_dump" in methods:
            self._exec_target("env | grep -iE 'key|secret|pass|token|api' || true")
        if "mounted_secrets" in methods:
            self._exec_target("find /run/secrets /vault/secrets /etc/secrets -type f 2>/dev/null | head -10 || true")

    def _recover_secret_exfiltration(self, fault: dict):
        pass

    def _inject_lateral_movement(self, fault: dict):
        methods = fault.get("methods", [])
        if "port_scan" in methods:
            # nc-based sweep — nmap may not be present
            self._exec_target(
                "for h in $(seq 1 10); do nc -zv 172.18.0.$h 80 2>&1 & done; wait || true"
            )
        if "arp_probe" in methods:
            self._exec_target("arp -a 2>/dev/null || true")
        if "dns_enum" in methods:
            self._exec_target("cat /etc/hosts && nslookup faultline-ddagent 2>/dev/null || true")

    def _recover_lateral_movement(self, fault: dict):
        pass

    def _inject_log_injection(self, fault: dict):
        payloads = fault.get("payloads", [])
        if "ansi_escape" in payloads:
            self._exec_target("echo -e '\\033[2J\\033[H INJECTED LOG CLEAR' || true")
        if "fake_auth_success" in payloads:
            self._exec_target("logger 'user=admin login=success src=10.0.0.1 method=password' || true")
        if "jndi_pattern" in payloads:
            # Inert string — no outbound network in airgapped env; tests SIEM rule matching on log content
            self._exec_target("logger '${jndi:ldap://169.254.169.254/latest/meta-data}' || true")

    def _recover_log_injection(self, fault: dict):
        pass

    def _inject_memory_scraping(self, fault: dict):
        patterns = fault.get("patterns", [])
        regexes = []
        if "api_key_regex" in patterns:
            regexes.append(r"[A-Za-z0-9_\-]{20,40}")
        if "jwt_regex" in patterns:
            regexes.append(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
        if "password_regex" in patterns:
            regexes.append(r"(password|passwd|pwd)=[^\s]+")

        for pid_cmd in ["pgrep python", "pgrep flask", "pgrep gunicorn"]:
            self._exec_target(
                f"for pid in $({pid_cmd} 2>/dev/null); do "
                f"strings /proc/$pid/mem 2>/dev/null | head -200 | grep -iE 'key|secret|pass|token' || true; "
                f"done"
            )

    def _recover_memory_scraping(self, fault: dict):
        pass

    def _exec_target(self, cmd: str, privileged: bool = False):
        container = self.sandbox.get_container("target")
        if not container:
            raise RuntimeError("Target container not found")
        exit_code, output = container.exec_run(
            ["/bin/sh", "-c", cmd],
            privileged=privileged,
        )
        if output:
            console.print(f"[dim]{output.decode().strip()}[/dim]")
        return exit_code
