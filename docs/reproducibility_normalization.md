# Wheel reproducibility normalization (WS14)

AKTA release CI builds the wheel twice and compares SHA-256 digests.

## Required build hygiene

Set a fixed timestamp so metadata is bit-stable across builds:

```bash
export SOURCE_DATE_EPOCH=1700000000
python -m build
python -m build -o dist-repro
```

CI sets `SOURCE_DATE_EPOCH` for both builds.

## Fail-closed rule

If digests differ after `SOURCE_DATE_EPOCH` is applied, the reproducibility job
**fails** unless an **active exception** token is listed below under
`## Active exceptions`.

Documented token vocabulary (do not put these in Active exceptions unless needed):

| Token | Meaning |
|-------|---------|
| `WHEEL_METADATA_TIMESTAMP` | setuptools still embeds non-deterministic RECORD/WHEEL metadata despite SOURCE_DATE_EPOCH (tooling bug; document version) |
| `PLATFORM_TAG_DRIFT` | Builder produced differing platform tags across runners (should not happen on identical ubuntu-latest jobs) |

Do **not** enable a token to soft-skip a real content drift in package code or
policy artifacts. Prefer fixing the build so digests match.

## Active exceptions

None.

## VSA pin

VSA is pinned to tag `v0.7.2` (`903d834f201535ac1525e3e8907254363209904f`) in
`policy/release_pins.yaml`. Missing checkout or SHA mismatch still fail-closes
under `institutional_release`; that is not a wheel reproducibility exception.
