"""The explainable match score (ADR-005, US-4.1).

**Located here rather than under `ml/ranking/`, despite ml.md section 8.**

`ml/` is not on the import path — `backend/` is the package root and the
Dockerfile copies only it — and these scorers run inside the request path, so
they must be importable by the API. Phase 6.1 set the same precedent one phase
earlier: ml.md specified `ml/embeddings/` and the provider shipped as
`app/integrations/embeddings/`. Following the document literally now would leave
the codebase inconsistent with itself.

The API image gains no ML dependency from any of this. Scoring is `Decimal`
arithmetic over ORM rows plus one cosine computed in SQL; nothing here imports
torch, and a test asserts it stays that way.

`ml/` keeps what genuinely belongs to it — Phase 6.4's offline evaluation, which
can `import app.services.matching` freely.
"""
