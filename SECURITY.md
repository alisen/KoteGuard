# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.0a3 (latest) | ✅ |
| < 1.0.0a3 | ❌ |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Use one of these private channels:

- **GitHub Private Vulnerability Reporting** — click "Report a vulnerability" on the [Security tab](https://github.com/alisen/KoteGuard/security/advisories/new)
- **Email** — [hello@koteguard.com](mailto:hello@koteguard.com)

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

### Response time

You will receive an acknowledgement within **48 hours** and a fix or mitigation plan within **7 days** for critical issues.

## Scope

KoteGuard handles:
- Git worktree isolation
- Sensitive file stubbing (`.jks`, `google-services.json`, `.p12`)
- Copilot CLI command generation with `--deny-tool` flags

Security issues in these areas are considered **high priority**.
