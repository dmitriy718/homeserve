# Security tools and boundaries

The gateway now exposes authenticated, audited security tools:

- `http_security_check`: status, redirects, server header, content type, and common security headers.
- `tcp_probe`: reachability and latency for an explicitly supplied host/port.
- `dns_lookup`: resolved addresses.
- `tls_certificate`: protocol, cipher, subject, issuer, and certificate dates.

Calls are written to `agent-audit.jsonl` without request bodies or credentials. These tools inspect services; they do not scan arbitrary networks, change UFW, change SSH, alter Docker, or execute host-root remediation. The gateway is containerized as UID 1000 without the host Docker socket and with workspace-only filesystem mounts. Host firewall changes remain an administrator action.

For an incident, the agent should first collect evidence with these tools, preserve the result in the artifact directory, and recommend or request the smallest corrective action.
