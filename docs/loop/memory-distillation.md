# Memory distillation — 5-step ladder

Only **verified** lessons enter `.claude/loop-memory.md` or the loop profile. Hypotheses stay out.

## Ladder

| Step | Name | Allowed into memory? | What happens |
|------|------|----------------------|--------------|
| 1 | **Fail** | No | Capture symptom + command/exit only (scratch, not memory). |
| 2 | **Investigate** | No | Form hypotheses; list candidates; do not promote. |
| 3 | **Verify** | No → gate | Reproduce with a concrete failing input / test / re-run. |
| 4 | **Distill** | **Yes** | One rule: cause → prevention; cite pin (`file:line` or test). |
| 5 | **Consult** | Yes (pointer) | Point future packs at the distilled rule and mark obsolete guidance. |

## Entry format (memory file)
Add one concise entry at the top of `.claude/loop-memory.md` and retain prior pack history.

```
## YYYY-MM-DD <PACK> — <VERDICT>
Revision and delivered change
Invariants checked
Gates and measured counts (passed / skipped where applicable)
Verified lesson and its evidence (test name, file:line, or artifact link)
```

## Hard rules
- Keep raw logs, transcripts, secrets, and unverified reviewer claims out of memory.
- For a blocked pack, record the verdict and observed evidence. Keep unresolved hypotheses in the pack evidence.
- If a lesson becomes obsolete, record the correction with current evidence and retain the historical verdict.
- Add only verified lessons to the profile's “Known pitfalls”.
