# Agent/build worker isolation

`scripts/run-agent-job.sh` creates one job directory under `/srv/builds/agents`, clones an HTTPS repository in a short-lived clone container, and runs the requested build command in a second disposable container.

The build container has no host root filesystem, Docker socket, SSH keys, credential stores, or unrelated repository mounts. It runs as UID 1000 with all Linux capabilities dropped, `no-new-privileges`, a read-only container root, no network, PID/CPU/RAM limits, and only the job workspace/artifact directories writable. Logs, the worktree, branch, and artifacts are retained; the container is destroyed.

The administrative user is in the Docker group, which is root-equivalent on the host. Do not expose the Docker socket to agent containers and do not let untrusted jobs invoke the host wrapper directly.

