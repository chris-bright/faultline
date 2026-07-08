#!/bin/bash
# Runs faultline as a privileged container with host namespace access.
# Required for network faults (tc, iptables) and time travel — these inject
# from outside the target container via nsenter, so the target image doesn't
# need any tools installed.
set -e

IMAGE="faultline:latest"

docker build -q -t "$IMAGE" .

docker run --rm \
  --pid=host \
  --cap-add=NET_ADMIN \
  --cap-add=SYS_PTRACE \
  --cap-add=SYS_ADMIN \
  -e DD_API_KEY \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/targets.yaml:/app/targets.yaml:ro" \
  -v "$(pwd)/scenarios:/app/scenarios:ro" \
  -v "/tmp/faultline:/tmp/faultline" \
  "$IMAGE" "$@"
