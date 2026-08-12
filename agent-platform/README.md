# AI Node Agent Platform

This platform provides an authenticated OpenAPI gateway and Open WebUI tool adapter for project workspaces.

- Gateway: `http://agent-gateway:8090` inside Docker; LAN/Tailscale port `8090`.
- Workspace root: `/srv/ai-node/agent-platform/workspaces` (mounted as `/srv/agent-workspaces` in the gateway).
- Artifact root: `/srv/ai-node/agent-platform/artifacts`.
- Tools: `fs_list`, `fs_read`, `fs_write`, `fs_mkdir`, `fs_delete`, `fs_hash`, and `shell_exec`.

Gateway tool, OpenAPI-schema, and transparency-data calls require the secret in `secrets/agent-gateway.env`; only the basic health endpoint and dashboard shell are intentionally readable on trusted networks. Paths are constrained to the workspace root. Shell commands run as the unprivileged `dima` UID in a project workspace and receive a minimal environment that excludes the gateway secret.

`AGENT_GATEWAY_KEY` must be at least 32 characters. Gateway writes are atomically published and limited to 5,000,000 bytes, hashes to 100,000,000-byte regular files, shell commands to 20,000 characters, and audit history rotates at 10 MiB. The container has a read-only root filesystem and no Linux capabilities; only the three scoped platform mounts and a small temporary filesystem are writable.

Open WebUI has both the external OpenAPI server and a native tool adapter configured. The installed qwen3:4b model can emit native tool calls through Ollama directly; Open WebUI's current chat path is still under compatibility testing (see the integration document).
