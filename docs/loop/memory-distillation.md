# Memory distillation — 5-step ladder

Only **verified** lessons enter `.claude/loop-memory.md` or the loop profile. Hypotheses stay out.

## Ladder

| Step | Name | Allowed into memory? | What happens |
|------|------|----------------------|--------------|
| 1 | **Fail** | No | Capture symptom + command/exit only (scratch, not memory). |
| 2 | **Investigate** | No | Form hypotheses; list candidates; do not promote. |
| 3 | **Verify** | No → gate | Reproduce with a concrete failing input / test / re-run. |
| 4 | **Distill** | **Yes** | One rule: cause → prevention; cite pin (`file:line` or test). |
| 5 | **Consult** | Yes (pointer) | Point future packs at the distilled rule; prune if obsolete. |

## Entry format (memory file)
Newest on top. One dense block per pack:

```
## YYYY-MM-DD <PACK> — <VERDICT>
What shipped · INV touched · gates (N passed) · rules distilled (verified only)
```

## Hard rules
- No logs, transcripts, or unverified reviewer claims.
- Adversarial findings default REFUTED until a failing input exists.
- If a distilled rule stops being true → delete or rewrite; never leave stale advice.
- Profile “Known pitfalls” ⊆ verified distillations only.
