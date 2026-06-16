from runner.runtime import ContainerRuntime, DockerRuntime


class Sandbox:
    """Attaches to a running container via the configured runtime."""

    def __init__(self, container_name: str, runtime: ContainerRuntime = None):
        self.container_name = container_name
        self.runtime = runtime or DockerRuntime()

    def attach(self):
        self.runtime.attach(self.container_name)

    def get_target_pid(self) -> int:
        return self.runtime.get_pid(self.container_name)
