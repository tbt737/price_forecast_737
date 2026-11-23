# Outcome Spec — template (fill one per PACK)

```
GOAL: <one sentence — what “done” means>

PASS_CRITERIA:
- P1: <binary, machine-checkable>
- P2: <binary, machine-checkable>
- P3: <optional>

EVIDENCE_REQUIRED:
- <exit code / stdout snippet / file:line / artifact path>
- Gate commands from `.claude/loop-profile.md` (paste exit codes + pass counts)

FORBIDDEN:
- <e.g. prod --write, deploy, workflow_dispatch, secret print, weaken INV tests>

BUDGET: max 3 fix→re-gate iterations / this unit

ESCALATION: ask human when budget exhausted, INV conflict, or scope unclear

OUT OF SCOPE: <intentional non-goals for this pack>
```

## Rules
- No PASS_CRITERIA ⇒ not a loop (chat only). Maker implements; Verifier scores.
- Criteria must be re-runnable by anyone with the repo + listed commands.
- Prefer pinning new behavior with a failing test first (tests-first).
