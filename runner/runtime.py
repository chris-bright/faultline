from abc import ABC, abstractmethod
import docker
from rich.console import Console

console = Console()


class ContainerRuntime(ABC):
    """
    Abstract interface for container operations.
    Implement for each supported runtime: Docker, Podman, Kubernetes, etc.
    FaultInjector and TelemetryCollector only call methods on this interface —
    they have no knowledge of the underlying runtime.
    """

    @abstractmethod
    def attach(self, container_name: str):
        """Verify the container exists and is running. Must be called before other methods."""
        ...

    @abstractmethod
    def get_pid(self, container_name: str) -> int:
        """Return the PID of the container's init process as seen on the host."""
        ...

    @abstractmethod
    def exec_run(self, container_name: str, cmd: str, privileged: bool = False) -> tuple[int, bytes]:
        """Execute cmd inside the container. Returns (exit_code, output)."""
        ...

    @abstractmethod
    def pause(self, container_name: str):
        """Suspend all processes in the container."""
        ...

    @abstractmethod
    def unpause(self, container_name: str):
        """Resume a paused container."""
        ...

    @abstractmethod
    def kill(self, container_name: str, signal: str = "SIGKILL"):
        """Send a signal to the container's main process."""
        ...


class DockerRuntime(ContainerRuntime):

    def __init__(self):
        self._client = docker.from_env()
        self._containers: dict[str, object] = {}

    def attach(self, container_name: str):
        try:
            container = self._client.containers.get(container_name)
            self._containers[container_name] = container
            console.print(f"[green]Attached:[/green] {container_name} ({container.short_id})")
        except docker.errors.NotFound:
            raise RuntimeError(f"Container '{container_name}' not found — is it running?")

    def get_pid(self, container_name: str) -> int:
        container = self._resolve(container_name)
        container.reload()
        pid = container.attrs["State"]["Pid"]
        if not pid:
            raise RuntimeError(f"Container '{container_name}' has no PID — is it running?")
        return pid

    def exec_run(self, container_name: str, cmd: str, privileged: bool = False) -> tuple[int, bytes]:
        container = self._resolve(container_name)
        exit_code, output = container.exec_run(["/bin/sh", "-c", cmd], privileged=privileged)
        return exit_code, output or b""

    def pause(self, container_name: str):
        self._resolve(container_name).pause()

    def unpause(self, container_name: str):
        self._resolve(container_name).unpause()

    def kill(self, container_name: str, signal: str = "SIGKILL"):
        self._resolve(container_name).kill(signal=signal)

    def _resolve(self, container_name: str):
        if container_name not in self._containers:
            raise RuntimeError(f"Container '{container_name}' not attached — call attach() first")
        return self._containers[container_name]


# --- Future runtime stubs ---

class PodmanRuntime(ContainerRuntime):
    """
    Podman implementation. Podman's REST API is Docker-compatible;
    this can likely reuse DockerRuntime pointed at the Podman socket.
    """
    def attach(self, container_name): raise NotImplementedError
    def get_pid(self, container_name): raise NotImplementedError
    def exec_run(self, container_name, cmd, privileged=False): raise NotImplementedError
    def pause(self, container_name): raise NotImplementedError
    def unpause(self, container_name): raise NotImplementedError
    def kill(self, container_name, signal="SIGKILL"): raise NotImplementedError


class KubernetesRuntime(ContainerRuntime):
    """
    Kubernetes implementation. Uses kubectl exec / pod lifecycle APIs.
    get_pid() requires privileged node access or a DaemonSet deployment.
    """
    def attach(self, container_name): raise NotImplementedError
    def get_pid(self, container_name): raise NotImplementedError
    def exec_run(self, container_name, cmd, privileged=False): raise NotImplementedError
    def pause(self, container_name): raise NotImplementedError
    def unpause(self, container_name): raise NotImplementedError
    def kill(self, container_name, signal="SIGKILL"): raise NotImplementedError
