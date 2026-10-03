# Agent instructions

Read [CLAUDE.md](CLAUDE.md) for the shared project rules, architecture, commands and data boundaries. Its name is retained for compatibility with Claude Code; those project rules also apply in Codex. This file adds the host-specific instructions below.

## Starting and continuing work

- Read the latest local numbered handoff and current plan as described in CLAUDE.md. Internal working documents may be absent from a fresh clone; report that instead of inventing their contents.
- Inspect the branch and working tree before changes. Continue an explicitly authorised task without asking for the same permission again. Ask about unresolved scope, policy or budget decisions.
- Run the prescribed checks for the task. During an ongoing session, reuse completed checks when the relevant code and environment have not changed; compaction alone does not require repeating a full release check.
- Keep context small: search before reading, return short findings, and link to saved evidence. At session close, write the next numbered local handoff without overwriting an earlier one.

## Codex and Windows

- Codex reads AGENTS.md. Do not assume it loads CLAUDE.md or `.claude/settings.json` automatically; read the shared rules explicitly.
- Claude Code hooks and review agents are host-specific. When the Claude-only review agent is unavailable, check handoffs directly against the local template and existing evidence.
- Codex hooks use a separate configuration. Reproduce failures with synthetic input before changing them. Keep machine-specific paths, diagnostics and configuration backups outside tracked files.
- The versioned project lifecycle configuration is [scripts/hooks/codex-hooks.json](scripts/hooks/codex-hooks.json). Install a local copy at `.codex/hooks.json`, preserving any existing local hooks, then review it in Codex. It reuses the handoff guard for SessionStart, PreCompact and non-blocking Stop; Windows commands resolve the repository root and virtual environment even from a subdirectory. `additionalContextLimit` bounds startup context, so read the full local handoff if the host supplies a shortened preview.
- In PowerShell, invoke a quoted executable path with the `&` call operator. Resolve Git Bash explicitly when required; bare `bash` may resolve to the WSL launcher. Use the repository virtual environment for Python.
- Prefer a hook's Windows command override to changing its portable command. Preserve failure exit codes. Never disable protection or edit trust records merely to remove an error; use the host's normal review process for changed definitions.
- Use the clarification tool available in the current host instead of assuming `AskUserQuestion` exists. Update persistent memory only when the owner explicitly requests it; the local decisions log and handoff remain the project record.
- Git data-guard hooks are independent of assistant hooks and remain mandatory. Do not bypass them with `--no-verify`.

Shared development and documentation rules: [DEVELOPMENT.md](docs/guides/DEVELOPMENT.md) and [DOCUMENTATION.md](docs/guides/DOCUMENTATION.md).
