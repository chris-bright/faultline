import docker
from pathlib import Path
from rich.console import Console

console = Console()

NETWORK_NAME = "faultline-isolated"


class Sandbox:
    def __init__(self, target_path: Path, client: docker.DockerClient):
        self.target_path = target_path
        self.client = client
        self.network = None
        self.containers = {}

    def up(self):
        self._ensure_network()
        self._start_target()
        console.print("[green]Sandbox up[/green]")

    def down(self):
        for name, container in self.containers.items():
            try:
                container.stop(timeout=5)
                container.remove()
                console.print(f"[dim]Removed container: {name}[/dim]")
            except Exception:
                pass
        if self.network:
            try:
                self.network.remove()
            except Exception:
                pass
        console.print("[dim]Sandbox torn down[/dim]")

    def get_container(self, name: str):
        return self.containers.get(name)

    def _ensure_network(self):
        try:
            self.network = self.client.networks.get(NETWORK_NAME)
            self.network.remove()
        except docker.errors.NotFound:
            pass
        self.network = self.client.networks.create(
            NETWORK_NAME,
            driver="bridge",
            internal=True,  # airgapped — no external routing
        )

    def _start_target(self):
        import os
        self.containers["target"] = self.client.containers.run(
            image=self._build_target_image(),
            name="faultline-target",
            network=NETWORK_NAME,
            detach=True,
            remove=False,
            mem_limit="256m",
        )

    def _build_target_image(self) -> str:
        # TODO: support pre-built images via --image flag so customers can point
        # faultline at their own registry image without a local Dockerfile.
        # Currently targets must be a local directory with a Dockerfile.
        tag = f"faultline-target:{self.target_path.name}"
        console.print(f"[dim]Building target image: {tag}[/dim]")
        self.client.images.build(
            path=str(self.target_path),
            tag=tag,
            rm=True,
        )
        return tag
