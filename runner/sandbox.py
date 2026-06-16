import docker
from rich.console import Console

console = Console()


class Sandbox:
    """Attaches to an already-running container. faultline does not manage container lifecycle."""

    def __init__(self, container_name: str, client: docker.DockerClient):
        self.container_name = container_name
        self.client = client
        self._container = None

    def attach(self):
        try:
            self._container = self.client.containers.get(self.container_name)
            console.print(f"[green]Attached:[/green] {self.container_name} ({self._container.short_id})")
        except docker.errors.NotFound:
            raise RuntimeError(f"Container '{self.container_name}' not found — is it running?")

    def get_container(self, name: str = "target"):
        return self._container
