# Security Policy

mcp-zero is an enterprise MCP gateway whose job is to enforce security. We take
vulnerabilities in the gateway itself seriously and appreciate responsible
disclosure.

## Supported Versions

The project is pre-1.0 and under active development. Security fixes are applied
to the latest released version and to `main`. Older versions are not patched.

| Version | Supported          |
| ------- | ------------------ |
| `main` / latest release | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately using either of the following:

1. **GitHub Private Vulnerability Reporting** (preferred) — open the
   repository's **Security** tab and click **Report a vulnerability**. This
   keeps the report private until a fix is published.
2. **Email** — contact the maintainer at **bryanw@abwaters.com** with details.

Please include, where possible:

- A description of the vulnerability and its impact.
- Steps to reproduce or a proof of concept.
- Affected version/commit and configuration (transport, policy file, identity
  settings) needed to trigger it.

## What to Expect

- **Acknowledgement** within 3 business days.
- An initial assessment and severity triage within 10 business days.
- Coordinated disclosure: we will work with you on a fix and a disclosure
  timeline, and credit you in the release notes unless you prefer to remain
  anonymous.

## Scope

Because this is a security gateway, we are particularly interested in reports
concerning:

- Authentication / identity bypass (Okta JWT validation, OBO token exchange).
- Governance / policy enforcement bypass (default-deny, server/tool/user/group
  controls).
- Data-protection failures (PII/secret masking via Presidio not applied on
  inputs or outputs).
- Audit-log integrity (missing, forgeable, or bypassable audit records).
- Transport-level issues across Streamable HTTP, SSE, and stdio.
- Secret or credential exposure (tokens, client secrets, JWTs).

Out of scope: vulnerabilities in upstream MCP servers or third-party
dependencies (report those to their maintainers; we still want to know if the
gateway mishandles them).
