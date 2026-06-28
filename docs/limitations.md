# AKTA Limitations

## v0.3

AKTA v0.3 hardens cross-repo integration with SCOPE, PF-Core, and PCS-Core. It explicitly does not:

- Replace SCOPE review routing, grant lifecycle, or reviewer identity verification
- Guarantee alignment with every SCOPE deployment variant without contract tests
- Run PF-Core or PCS-Core validation in CI when those repositories are unavailable locally
- Load arbitrary classifier plugins without explicit registration (plugin hook is illustrative)
- Certify domain overlays as complete safety coverage (overlays remain illustrative)
- Emit global permissions from narrow scoped grants

### v0.3 integration limits

- **SCOPE alignment**: `requested_scope` uses a fixed enum validated at emission; SCOPE repo code is simulated via `tests/contracts/scope_fixtures.py` when not present locally
- **PF/PCS cross-repo CI**: Contract tests use pinned fixtures mimicking external repo shapes; full cross-repo CI requires sibling checkouts
- **Classifier plugin hook**: Registration API exists; default kernel remains deterministic rule-based
- **Domain overlays**: Hazard triggers and scope overrides are illustrative, not EHS-certified

### Trusted boundary assumptions (v0.3)

- Tool-to-scope mapping in `policy/tool_to_requested_scope.yaml` is reviewed before deployment
- Runtime enforces AKTA decisions and PF obligations before mutating tools
- SCOPE grants are scoped; AKTA re-evaluates or PF blocks out-of-scope tool calls

## v0.2

AKTA v0.2 added per-action evidence rules, consequentiality, SCOPE-compatible review triggers (v0.2 vocabulary), PF obligation export, PCS bundles, and AKTA-Bench 100 scenarios. It does not replace formal authorization or release verification.

## v0.1

AKTA v0.1 is a reference kernel for scientific action admissibility. It explicitly does not:

- Decide scientific truth or correctness
- Replace evidence retrieval or scientific report generation (see VSA)
- Replace formal runtime authorization (see PF-Core)
- Replace release packaging and verification (see PCS-Core)
- Certify autonomous labs or safety compliance
- Replace EHS, IRB, biosafety, chemical safety, clinical review, or legal compliance
- Support fully autonomous scientific operation (P7 is taxonomy-only)
- Guarantee model truthfulness, tool honesty, or reviewer competence

### Trusted boundary assumptions (v0.1)

- Input context is provided honestly or marked uncertain
- Tool registry correctly describes tool effects
- Deployment profile is correctly configured
- Domain overlay is reviewed before deployment
- Runtime harness enforces AKTA decisions

## Non-certification

The AKTA Card describes system deployment characteristics. It is not a safety certification.
