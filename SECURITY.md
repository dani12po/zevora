# Security Policy

## Reporting a Vulnerability

Please report security issues privately to the maintainers before disclosure.
Open an issue only for non-sensitive bugs. Do not include secrets, API keys, or
model credentials in any report.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Current | :white_check_mark: |

## Security Posture

ZEVORA is a local-first coding agent. This section documents the built-in
boundaries that protect the host and the network.

### Local model integrity
- Local GGUF models are verified by SHA-256 before loading when an authoritative
  reference exists (`<model>.sha256` sidecar or the managed-package manifest).
- A mismatched digest aborts the load; the managed-package installer writes a
  sidecar for every package it places.
- The agent never downloads a whole Hugging Face repository; it selects a single
  quantization package.

### Provider request surface (SSRF)
- Cloud provider base URLs are validated at construction time
  (`agent/providers/ssrf.py`).
- Requests to loopback, link-local (including `169.254.169.254` cloud metadata),
  unspecified addresses, reserved metadata hostnames, and non-http(s) schemes are
  rejected.
- Local/OpenAI-compatible loopback endpoints are a separate provider class and
  are not routed through this guard.

### Workspace and permissions
- File, terminal, git, and package operations are gated by the permission system.
- Approved approvals never override workspace-boundary restrictions: paths
  outside the workspace are blocked even when approved.

### Secrets and telemetry
- Provider credentials are stored as environment references, never embedded in
  manifests or logs.
- Telemetry and logged traces are redacted of API keys and model credentials.

### Cache and memory
- The semantic/exact cache key includes a model signature, so cached responses
  for one model/quantization are never replayed for another.
- Prompt-injection defenses and output sanitization are applied to knowledge and
  memory flows.

## Reporting Process

1. Describe the vulnerability, impact, and reproduction steps.
2. Maintainers will acknowledge within 5 business days.
3. A fix is coordinated before public disclosure, unless the issue is publicly
   exploitable now, in which case it is disclosed immediately.
