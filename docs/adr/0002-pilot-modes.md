# ADR 0002 — Pilot modes

## Status

Accepted (AKTA-AS-00; implemented in AS-05)

## Context

Pre-AS pilot stages (`stage1_shadow`, `stage2_draft_only`, `stage3_validation`) underspecify tool restrictions and do not match the five institutional pilot modes required for hardening. REST/MCP also use a separate “mode” namespace for deployment identity.

## Decision

Introduce five first-class `PilotMode` values:

| Mode | Hard restrictions |
|------|-------------------|
| `retrospective_reconstruction` | No live tool execution; reconstruct/validate only |
| `prospective_shadow` | Full evaluate + record; `shadow=true`; must not drive allow/execute side effects; comparison record required |
| `read_only_support` | Mutating/execution tools blocked; analysis/query only |
| `execution_adjacent` | Draft/propose/review tools allowed; direct execution tools blocked |
| `bounded_execution` | Full stack profile + trust pins required; tool allowlist from policy; fail closed on missing trust |

Legacy `PilotStage` / `AKTA_PILOT_STAGE` aliases map into these modes. Unknown values fail closed.

### Policy profile binding

Each mode loads a profile under `policy/pilot_modes/` validated by `pilot_mode_profile.schema.json`. Profiles declare tool-effect allow/deny classes and trust requirements.

### Shadow isolation

`prospective_shadow` decisions must set `operational_influence: false`. Shadow responses must never authorize execution via grant/export paths that enable side effects.

### CLI naming

- `akta gate --mode <pilot_mode>` — pilot mode (this ADR)
- REST service `--mode` — deployment identity (unchanged; different namespace)

Default without `--mode` preserves pre-AS-05 behavior (retrospective-compatible / current `stage1_shadow` env default).

## Consequences

- AS-05 enforces mode gates before tool-resolution side effects.
- AS-07 metrics consume shadow comparison artifacts.
- Documentation must disambiguate pilot mode vs REST deployment mode.
