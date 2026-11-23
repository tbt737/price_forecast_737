# Outcome Spec — template (fill one per PACK)

```
PACK_NAME: <name>
GOAL: <one sentence describing the outcome>
BASE_REVISION: <commit SHA>
ALLOWED_WRITES: <explicit paths or outputs>
INVARIANTS: <applicable contracts from the loop profile>

PASS_CRITERIA:
- P1: <command or check, input or fixture, expected exit code or value>
- P2: <command or check, input or fixture, expected exit code or value>

EVIDENCE_REQUIRED:
- <map each P* to a command result, test, or artifact>
- <profile gate commands, exit codes, and pass/skip counts>
- <offline smoke command, target, and expected result, if applicable>
- <adversarial review result when required by the profile>

FORBIDDEN:
- Profile restrictions apply. List any additional restrictions for this pack.

BUDGET: max 3 fix→re-gate cycles, 2 adversarial fix rounds, 2 smoke retries
STOP: first PASS, repeated failure without progress, oscillation, or exhausted budget
ESCALATION: <unresolved evidence, conflicting invariants, or approval required>

OUT OF SCOPE: <explicitly excluded work>
```

## Rules
- Define the named pack and measurable PASS criteria before starting execution. Every listed P* is required.
- Give each criterion a reproducible command or check, inputs, and an expected result.
- Retry only to address a specific failing criterion or gap. Report the blocking evidence if a stop condition is reached before PASS.
- Freeze the criteria for review. The Maker implements and an independent Verifier scores the result.
