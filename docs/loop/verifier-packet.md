# Verifier packet — what the Verifier may receive

Maker ≠ Verifier. The Verifier **must not** see Maker reasoning, chain-of-thought, or “trust me” prose.

## Inputs (only these)
1. **Outcome Spec** — verbatim, including all PASS criteria, scope, and stop conditions.
2. **Revision under review** — candidate SHA and its complete diff (with the base SHA) or the complete artifact at that SHA.
   Include new files in the diff. A file list or diffstat alone is insufficient.
3. **Verification evidence** — gate commands, exit codes, pytest/vitest pass and skip counts, smoke results
   when required, and evidence references mapped to each criterion. Use the candidate SHA for all results.

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
- Return `PASS` only when every P* passes with evidence from the revision under review.
- Return `FAIL` for a failed criterion or missing evidence the Maker can supply. Use `ESCALATE` when evidence
  remains unresolved or a scope, budget, or invariant conflict requires a decision.
- Cite a failed command, a concrete diff location, or an artifact reference for each gap.
- The Verifier may re-run gates within the Outcome Spec and stays read-only with respect to the candidate.
- If the candidate changes, review the new SHA and its evidence before issuing a verdict.
