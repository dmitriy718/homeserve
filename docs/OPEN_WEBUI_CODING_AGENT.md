# Homeserv interactive coding agent

Open `https://webui.homeserve.lan`, sign in through Authelia, and start a chat with `Homeserv Coding Agent`. The Agent Gateway is selected automatically. Workspace shell commands run in `ai-agent-shell` as UID 10001, with a four-hour limit. The `host_exec` tool runs on Homeserv as root and can access system files, Docker, SSH, and network utilities. It can reach the Windows laptop `aidev` as `dmitr`; the Windows Desktop is `C:\Users\dmitr\Desktop`. Open WebUI asks for approval before tool calls; inspect the proposed call and approve it to proceed.

The initial project workspace is `/srv/ai-node/agent-platform/workspaces/nova-store-intelligence`. It is a copy of the available `.source-be94959` snapshot, not the operational service directory. The copy intentionally omits `node_modules`, production state, backups, and secrets. The snapshot is missing its pnpm workspace and lock files and has an unresolved `sharp` catalog reference; package installation is blocked until the full source checkout or missing metadata is restored. Keep work inside this workspace and review changes before copying or deploying them elsewhere.

The source project's `AGENTS.md` requires explicit owner approval for risky live actions. Never let a chat agent deploy to production, write to Shopify, touch finance/tax settings, or change credentials without a separate approval for that specific action. The gateway's filesystem boundary limits reachable paths, but shell commands are otherwise general-purpose inside the workspace and have outbound internet access.

The Agent Host executor has root-equivalent access to Homeserv. Keep host operations in the tool approval flow and check the command and working directory before approving.
