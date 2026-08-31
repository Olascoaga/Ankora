# Ankora agent policy

This policy applies to Codex, Claude Code, and any other implementation or review agent.

Before modifying code, read completely:

1. `CODEX_BOOTSTRAP.md`

When the local, Git-ignored `memory/` workspace is present, also read completely:

1. `memory/START_HERE.md`
2. `memory/PROJECT_STATE.md`
3. `memory/NEXT_SESSION.md`

`memory/` is private local continuity state. Never stage or publish it. A fresh
clone may not contain it; in that case use the tracked contract, ADRs,
validation records, and Git history as the public handoff.

## Required behavior

- Do not expand scope without explicit authorization.
- Never silently replace scientific behavior with a shortcut.
- A capability is complete only when implementation, tests, acceptance criteria, and recorded validation evidence exist.
- Preserve raw outputs from external scientific tools.
- Prefer structured APIs and outputs; do not parse human-readable logs when structured data exists.
- Never invent scientific results in tests. Label synthetic fixtures, and derive reference expectations from recorded evidence.
- The frontend must never invoke Vina, GNINA, Meeko, or other scientific executables directly.
- Detect and record external tool versions whenever tools are used.
- Windows-native behavior is authoritative.
- Keep original imported artifacts immutable and propagate stale state to dependent derivatives.
- Bind local services only to localhost and construct subprocess calls with argument arrays.

## Session protocol

- Codex implements; Claude Code may audit or review.
- Do not allow two agents to edit the same branch concurrently.
- During an explicitly authorized implementation sequence, finish work in bounded units and commit each completed unit after its relevant tests and tracked documentation updates. Keep commits small and cohesive; do not wait for the scientist to repeat the commit instruction.
- Before ending a coding session, run available tests and update the tracked project documentation. When the local `memory/` workspace exists, update `memory/PROJECT_STATE.md` and `memory/NEXT_SESSION.md` and record important decisions in `memory/DECISIONS.md`, but never stage those private files.
