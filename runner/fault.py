import shutil
import subprocess
from rich.console import Console

console = Console()


class FaultNotApplied(Exception):
    """Raised when a fault cannot be injected because a required tool is missing."""


class FaultInjector:
    """Injects faults via host namespace (nsenter) when available, falls back to container exec."""

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self._host_mode = shutil.which("nsenter") is not None
        if self._host_mode:
            console.print("[dim]Host namespace injection available (nsenter)[/dim]")

    @property
    def _runtime(self):
        return self.sandbox.runtime

    @property
    def _target(self):
        return self.sandbox.container_name

    def inject(self, fault: dict) -> bool:
        fault_type = fault["type"]
        handler = getattr(self, f"_inject_{fault_type}", None)
        if not handler:
            raise ValueError(f"Unknown fault type: {fault_type}")
        exit_code = handler(fault)
        if exit_code and exit_code != 0:
            console.print(f"[bold yellow]Warning: fault injection returned exit code {exit_code}[/bold yellow]")
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
        if self._host_mode:
            subprocess.Popen(["stress-ng", "--cpu", str(cores), "--timeout", f"{duration}s"])
            return 0
        self._require_tool("stress-ng")
        return self._exec_target(f"cd /tmp && stress-ng --cpu {cores} --timeout {duration}s &")

    def _recover_cpu_stress(self, fault: dict):
        if self._host_mode:
            subprocess.run(["pkill", "stress-ng"], capture_output=True)
        else:
            self._exec_target("pkill stress-ng || true")

    def _inject_memory_pressure(self, fault: dict):
        mb = fault.get("mb", 128)
        if self._host_mode:
            subprocess.Popen(["stress-ng", "--vm", "1", "--vm-bytes", f"{mb}M", "--timeout", "60s"])
            return 0
        self._require_tool("stress-ng")
        return self._exec_target(f"cd /tmp && stress-ng --vm 1 --vm-bytes {mb}M --timeout 60s &")

    def _recover_memory_pressure(self, fault: dict):
        if self._host_mode:
            subprocess.run(["pkill", "stress-ng"], capture_output=True)
        else:
            self._exec_target("pkill stress-ng || true")

    def _inject_process_freeze(self, fault: dict):
        self._runtime.pause(self._target)
        console.print("[dim]Container paused via cgroups freezer[/dim]")

    def _recover_process_freeze(self, fault: dict):
        try:
            self._runtime.unpause(self._target)
        except Exception:
            pass

    def _inject_disk_fill(self, fault: dict):
        mb = fault.get("mb", 100)
        self._exec_target(f"dd if=/dev/zero of=/tmp/faultline_fill bs=1M count={mb} &")

    def _recover_disk_fill(self, fault: dict):
        self._exec_target("rm -f /tmp/faultline_fill")

    def _inject_packet_loss(self, fault: dict):
        pct = fault.get("percent", 20)
        return self._exec_netns(f"tc qdisc add dev eth0 root netem loss {pct}%")

    def _recover_packet_loss(self, fault: dict):
        self._exec_netns("tc qdisc del dev eth0 root 2>/dev/null || true")

    def _inject_bandwidth_cap(self, fault: dict):
        rate = fault.get("rate", "1mbit")
        return self._exec_netns(f"tc qdisc add dev eth0 root tbf rate {rate} burst 32kbit latency 400ms")

    def _recover_bandwidth_cap(self, fault: dict):
        self._exec_netns("tc qdisc del dev eth0 root 2>/dev/null || true")

    def _inject_packet_corruption(self, fault: dict):
        pct = fault.get("percent", 5)
        return self._exec_netns(f"tc qdisc add dev eth0 root netem corrupt {pct}%")

    def _recover_packet_corruption(self, fault: dict):
        self._exec_netns("tc qdisc del dev eth0 root 2>/dev/null || true")

    def _inject_dns_blackhole(self, fault: dict):
        return self._exec_netns(
            "iptables -I OUTPUT -p udp --dport 53 -j DROP && iptables -I OUTPUT -p tcp --dport 53 -j DROP"
        )

    def _recover_dns_blackhole(self, fault: dict):
        self._exec_netns(
            "iptables -D OUTPUT -p udp --dport 53 -j DROP 2>/dev/null || true && "
            "iptables -D OUTPUT -p tcp --dport 53 -j DROP 2>/dev/null || true"
        )

    def _inject_network_partition(self, fault: dict):
        return self._exec_netns("iptables -I OUTPUT -j DROP")

    def _recover_network_partition(self, fault: dict):
        self._exec_netns("iptables -F OUTPUT 2>/dev/null || true")

    def _inject_process_kill(self, fault: dict):
        self._runtime.kill(self._target, signal="SIGKILL")

    def _recover_process_kill(self, fault: dict):
        pass

    def _inject_time_travel(self, fault: dict):
        offset = fault.get("offset_seconds", 3600)
        return self._exec_utsns(
            f"date -s \"$(date -d '+{offset} seconds' '+%Y-%m-%d %H:%M:%S')\""
        )

    def _recover_time_travel(self, fault: dict):
        self._exec_utsns("hwclock -s 2>/dev/null || ntpdate -u pool.ntp.org 2>/dev/null || true")

    # --- Code ---

    def _inject_dependency_killed(self, fault: dict):
        dep = fault.get("service")
        if dep:
            self._runtime.pause(dep)
            console.print(f"[dim]Paused dependency: {dep}[/dim]")

    def _recover_dependency_killed(self, fault: dict):
        dep = fault.get("service")
        if dep:
            try:
                self._runtime.unpause(dep)
            except Exception:
                pass

    def _inject_latency_injection(self, fault: dict):
        ms = fault.get("ms", 500)
        return self._exec_netns(f"tc qdisc add dev eth0 root netem delay {ms}ms")

    def _recover_latency_injection(self, fault: dict):
        self._exec_netns("tc qdisc del dev eth0 root 2>/dev/null || true")

    # --- Container ---

    def _inject_oom_kill(self, fault: dict):
        if self._host_mode:
            subprocess.Popen(["stress-ng", "--vm", "1", "--vm-bytes", "512M", "--timeout", "10s"])
            return 0
        self._require_tool("stress-ng")
        return self._exec_target("stress-ng --vm 1 --vm-bytes 512M --timeout 10s &")

    def _recover_oom_kill(self, fault: dict):
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
        pass

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
        checks = [
            "sudo id 2>&1 || true",
            "find / -perm -4000 -type f 2>/dev/null | head -5 || true",
            "cat /proc/1/status 2>&1 | grep -i cap || true",
            "id",
        ]
        for cmd in checks:
            self._exec_target(cmd)

    def _recover_privilege_escalation(self, fault: dict):
        pass

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
            self._exec_target("logger '${jndi:ldap://169.254.169.254/latest/meta-data}' || true")

    def _recover_log_injection(self, fault: dict):
        pass

    def _inject_memory_scraping(self, fault: dict):
        for pid_cmd in ["pgrep python", "pgrep flask", "pgrep gunicorn"]:
            self._exec_target(
                f"for pid in $({pid_cmd} 2>/dev/null); do "
                f"strings /proc/$pid/mem 2>/dev/null | head -200 | grep -iE 'key|secret|pass|token' || true; "
                f"done"
            )

    def _recover_memory_scraping(self, fault: dict):
        pass

    # --- Execution helpers ---

    def _exec_netns(self, cmd: str) -> int:
        """Run cmd inside the target container's network namespace from the host."""
        if not self._host_mode:
            raise FaultNotApplied(
                "Host namespace injection not available — run faultline via faultline.sh to enable network faults"
            )
        pid = self.sandbox.get_target_pid()
        result = subprocess.run(
            ["nsenter", f"--net=/proc/{pid}/ns/net", "--", "/bin/sh", "-c", cmd],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            console.print(f"[dim]{result.stdout.strip()}[/dim]")
        if result.stderr.strip():
            console.print(f"[dim]{result.stderr.strip()}[/dim]")
        return result.returncode

    def _exec_utsns(self, cmd: str) -> int:
        """Run cmd inside the target container's UTS namespace (hostname/time)."""
        if not self._host_mode:
            raise FaultNotApplied(
                "Host namespace injection not available — run faultline via faultline.sh to enable time travel faults"
            )
        pid = self.sandbox.get_target_pid()
        result = subprocess.run(
            ["nsenter", f"--uts=/proc/{pid}/ns/uts", "--", "/bin/sh", "-c", cmd],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            console.print(f"[dim]{result.stdout.strip()}[/dim]")
        return result.returncode

    def _exec_target(self, cmd: str, privileged: bool = False) -> int:
        """Run cmd inside the target container via the runtime (fallback / security probes)."""
        exit_code, output = self._runtime.exec_run(self._target, cmd, privileged=privileged)
        if output:
            console.print(f"[dim]{output.decode().strip()}[/dim]")
        return exit_code

    def _require_tool(self, *tools: str):
        """Raise FaultNotApplied if any required tool is missing from the target container."""
        for tool in tools:
            exit_code, _ = self._runtime.exec_run(self._target, f"command -v {tool} >/dev/null 2>&1")
            if exit_code != 0:
                raise FaultNotApplied(
                    f"Required tool '{tool}' not found in container — run faultline via faultline.sh for host-level injection"
                )
