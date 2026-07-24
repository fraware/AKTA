# Extracting `scientific-authorization-contracts` to an independent repository

## Status

**In-tree publishable source:** this directory remains the authoritative source for
`scientific-authorization-contracts==2.2.0` until an independent GitHub repository
is created and CI publishes wheels from it.

**Blocker:** creating `github.com/<org>/scientific-authorization-contracts` requires
org credentials / permissions not available in the SCOPE agent environment. Leave
this package in the monorepo as the wheel build root; SCOPE pins by version (+ hash
when the release identity artifact is filled in CI).

## Target layout (independent repo)

```
scientific-authorization-contracts/
  pyproject.toml
  README.md
  LICENSE
  src/scientific_authorization_contracts/
    __init__.py
    envelope.py
    operations.py
    targets.py
    environments.py
    cardinality.py
    constraints.py
    expiration.py
    runtime_request.py
    hashing.py
    grant.py
    status.py
    manifest.py
    loaders.py
    errors.py
    schemas/
    vocabularies/
    conformance/
  tests/
  .github/workflows/publish.yml
  release_identity/
    scientific-authorization-contracts-2.2.0.json
```

## Extraction steps

1. `git subtree split -P scientific-authorization-contracts -b contracts-split`
   (or copy the subtree into a new empty repo preserving history).
2. Point `project.urls` at the new repository.
3. Publish `2.2.0` wheel + sdist; write SHA-256 digests into the release identity JSON.
4. Update SCOPE `pyproject.toml` / CI lockfile to `pip install --require-hashes`.
5. Remove the subtree from SCOPE once consumers install from the registry; keep thin
   facades under `scope/authorization_envelope.py` and `scope/contract_loader.py`.

## SemVer rule

Any change to containment, algebra, schemas, vocabularies, or hash canonicalization
bumps **this** package (not only SCOPE).
