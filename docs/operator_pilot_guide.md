# Operator pilot guide

How to run an institutional AKTA pilot without treating gate outputs as truth certification or execution authority.

## Non-claims

- AKTA admits/refuses proposed actions under pinned policy — it does not certify scientific truth or efficacy.
- Shadow mode must not drive operational allow/execute side effects.
- Pilot metrics are operational aggregates, not institution-wide scientific efficacy scores.

## Pilot modes (AS-05)

These are **PilotMode** values for `akta gate --mode`. They are not REST service deployment modes (`development-local` / `pilot-service` / `institutional-service`) and not legacy `PilotStage` enum names (those aliases map into PilotMode; unknown values fail closed).

| Mode | Operator use |
|------|----------------|
| `retrospective_reconstruction` | Rebuild/validate historical releases only |
| `prospective_shadow` | Evaluate + record with `shadow=true`; compare to human decisions; must not drive allow/execute side effects |
| `read_only_support` | Analysis/query assistance; no mutations |
| `execution_adjacent` | Draft/propose/review; no direct execution |
| `bounded_execution` | Requires stack profile + trust pins; tool allowlist; fail closed |

```bash
akta gate --ai-text "..." --tool analysis.literature_summary --mode prospective_shadow --out decision.json
akta record --decision decision.json --out akta_record.json
akta validate-stack-profile stack_profile.json
```

## Release reconstruction

```bash
akta reconstruct --release action_release/ --out reconstruction.json
```

Expect `ok=true`, bindings present, and checksums for the bundle.

## Outcomes and metrics

```bash
akta link-outcome --record akta_record.json --outcome-ref outcome_ref.json --out akta_record_linked.json
akta export-pilot-metrics --records records/ --out metrics.json
```

Outcome links are append-only and must not change `admissibility`.

## Checklist

1. Pin policy / overlays / tool registry; record `bindings` digests
2. Choose pilot mode explicitly; default without `--mode` preserves pre-AS-05 behavior
3. For institutional / `bounded_execution`, run `akta validate-stack-profile` (incomplete pins and placeholder release signers remain fail-closed)
4. Export SCOPE trigger → PF → PCS with binding fields intact
5. Run `akta reconstruct` before treating a release as pilot-complete

See [stack_profile.md](stack_profile.md), [adr/0001-admissibility-boundary.md](adr/0001-admissibility-boundary.md), [adr/0002-pilot-modes.md](adr/0002-pilot-modes.md), and [limitations.md](limitations.md).
