# Classifier Trust Boundary (v0.5)

AKTA treats deterministic classification as authoritative. Optional LLM classifiers operate in an **advisory-only** trust zone and never override known tool-registry mappings.

## Trust zones

| Zone | Source | Authority |
|------|--------|-----------|
| **Deterministic** | Tool registry, structured action, requested-action keywords | Authoritative for admissibility |
| **LLM advisory** | `OptionalLLMClassifierPlugin` when enabled | Proposes action type only when registry cannot resolve |
| **Conservative fallback** | `ConservativeFallbackClassifierPlugin` | Default when all else fails |

## Tool registry override

When `tool_spec.known` is true, the tool registry mapping **always** wins over LLM output. The classifier records `llm_overridden_by_tool_registry` in uncertainty flags when an LLM plugin would have suggested a different type.

## LLM advisory metadata

When `classifier_mode` is `llm_advisory`, the AKTA Decision includes:

- `classification.classifier_mode`: `llm_advisory`
- `llm_advisory.model`: model identifier
- `llm_advisory.prompt_hash`: SHA-256 of system prompt + user text
- `llm_advisory.schema`: `akta_classification_v0.5`
- `llm_advisory.confidence`: model-reported confidence

## Fail-closed for mutating and external tools

If LLM advisory confidence is below 0.7 and the requested tool is mutating, external-effect, or unknown, admissibility resolves to `abstain_insufficient_context`.

## Enabling LLM classifier

```bash
export AKTA_LLM_CLASSIFIER=1
export OPENAI_API_KEY=sk-...
# optional: export AKTA_LLM_MODEL=gpt-4o-mini
```

Without `OPENAI_API_KEY`, the LLM plugin is disabled (fail-closed).

## Production guidance

- Do not treat LLM classification as policy authority.
- Pin policy bundle version and verify integrity (`AKTA_PRODUCTION_MODE=1`).
- Audit `llm_advisory` fields in AKTA Records when LLM path is enabled.
