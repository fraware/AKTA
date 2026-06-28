# Reconstruction Report

Regenerate: `python scripts/demo_reconstructable_experiment.py` or `make demo-reconstructable`

Canonical artifact chain is written to `dist/reconstructable_experiment/` (not checked into git by default).

## Policy layers: SCOPE grant vs AKTA re-gate

AKTA and SCOPE operate as separate enforcement layers:

1. **SCOPE** issues a scoped authorization grant (`single_run_queue_priority`, `protocol_draft`, etc.) after human review. The grant may include `allowed_tools` and `blocked_tools`.
2. **AKTA re-gate** (`evaluate_with_grant`) applies grant metadata to context via `prior_review_allowed_tools` and `prior_review_blocked_tools`, then re-evaluates the requested action against deployment profile, evidence matrix, and domain overlay.
3. **SCOPE grants do not override AKTA evidence/profile policy** unless the deployment profile explicitly permits the action at the current evidence state. A narrow SCOPE grant can authorize scope rank, but weak evidence under `P2_analysis_assistant` may still block queue prioritization.

Case C in the demo asserts an explicit post-grant admissibility decision. AKTA must not silently pass when evidence policy still blocks the action.

## Demo cases

| Case | Step | Expected |
|------|------|----------|
| A | Weak evidence (`E2`) + `P2_analysis_assistant` + `lab_scheduler.prioritize` | `blocked` or `review_required` before SCOPE |
| B | SCOPE grants `single_run_queue_priority` | Grant artifact with approved scope |
| C | AKTA re-gate same tool with grant | Explicit decision; remains blocked under P2/E2 (not silent pass) |

## Linkage

See generated `reconstruction_report.md` in `dist/reconstructable_experiment/` for artifact linkage checks after each run.

Public release verification: [docs/RELEASE.md](../../docs/RELEASE.md).
