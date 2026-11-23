# Verifier packet — what the Verifier may receive

Maker ≠ Verifier. The Verifier **must not** see Maker reasoning, chain-of-thought, or “trust me” prose.

## Inputs (only these)
1. **Outcome Spec** — verbatim (GOAL / PASS_CRITERIA / EVIDENCE / FORBIDDEN / BUDGET / OUT OF SCOPE)
2. **Changed files** — path + one-line description each (`git diff --stat` + short notes OK)
3. **Machine gate output** — exit codes + summary lines (pytest/vitest counts, ruff/mypy/build)

## Verifier returns (exact shape)

```
RESULT: PASS | FAIL | ESCALATE

CHECKS:
- P1=<PASS|FAIL> <evidence ref>
- P2=<PASS|FAIL> <evidence ref>

GAPS: <criterion id + file:line> | (empty)

NOTES: <optional one-liners; no Maker transcripts>
```

## Decision rules
- Any P* FAIL ⇒ `FAIL` (not PASS with caveats).
- Missing evidence for a P* ⇒ `FAIL` or `ESCALATE` (fail-closed; do not invent).
- Scope / budget / INV conflict ⇒ `ESCALATE` + ask human.
- Verifier may re-run gates; may not edit product code in the same role.
