---
applyTo: "**/*"
---

# Security Instructions (KoteGuard)

> These instructions apply to ALL files in this worktree.

## Deny-by-Default Rules

1. **No secrets in source code** – never hardcode API keys, tokens, passwords.
2. **No git push** – humans review all changes before they leave this worktree.
3. **No branch creation outside kote/** – stay on the assigned branch.
4. **No file exfiltration** – do not print or upload file contents to external services.

## Android

- NEVER read, copy, or output contents of: `*.jks`, `*.keystore`, `google-services.json`
- `local.properties` must never be committed
- Do not add signing config with hardcoded passwords

### Android CLI Commands

**Allowed:** `android list avd`, `android list targets`, `android list sdk`
**Forbidden (outside worktree):** `android run`, `android emulator`

## iOS

- NEVER read, copy, or output contents of: `*.p12`, `*.mobileprovision`, `GoogleService-Info.plist`
- Do not hardcode API keys or bundle IDs in source files

## Allowed Git Commands

- `git status`, `git diff`, `git log` – read-only inspection
- `git add`, `git commit` – staging and committing changes
- `git stash` – temporary stash

## Forbidden Git Commands

- `git push` – forbidden without human review
- `git remote add` – forbidden
- `git remote set-url` – forbidden
- `git clone` – forbidden inside worktree
