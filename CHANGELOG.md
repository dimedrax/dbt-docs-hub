# Changelog

All notable changes to the dbt Docs Hub will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Apache 2.0 LICENSE.
- `SECURITY.md` with vulnerability reporting policy and security model
  (fail-closed by design).
- `CONTRIBUTING.md` with dev setup (uv) and PR checklist.
- `CHANGELOG.md` (this file).
- `pyproject.toml` `[tool.ruff]` configuration on both services
  (`E`, `F`, `I`, `B`, `UP`, `SIM`, `RUF` rule sets).
- `pyproject.toml` `[dependency-groups]` `dev` block with `pytest`,
  `respx`, and `ruff`.
- 27 pytest tests covering the security-critical modules
  (`policy_engine.py`: paths and fail-closed behaviour;
  `jwt_utils.py`: claim extraction with malformed/edge-case tokens).
- GitHub Actions `ci` workflow: ruff lint + format check + pytest +
  Docker image build (no-push) for both services on push and PR.
- Healthcheck on `dbtdocs-web` (oauth2-proxy stays uncovered — the
  official image is distroless).

### Changed

- Decoupled the Filtering API from OPA naming: `opa_client.py` →
  `policy_engine.py`, `OPA_URL` → `POLICY_ENGINE_URL`, log lines
  reference "Policy Engine" instead of "OPA". The wire contract stays
  OPA-compatible (POST `/v1/data/dbtdocs/*`, body `{input}` →
  `{result}`). OPA remains the default implementation, shipped under
  `examples/opa-policies/`.
- Renamed services for role clarity: `dbtdocs-fastapi` →
  `dbtdocs-filtering-api`, `dbtdocs-sidecar` → `dbtdocs-indexer`,
  `dbtdocs-nginx` → `dbtdocs-web`. Folders renamed accordingly
  (`fastapi/` → `filtering_api/`, `sidecar/` → `indexer/`).
- Migrated both services from `pip` + `requirements.txt` to `uv` +
  `pyproject.toml` + committed `uv.lock`. Multi-stage Dockerfiles
  produce smaller images (filtering-api 480 MB → 306 MB; indexer
  382 MB → 252 MB) than the single-stage uv build.
- Externalized OPA: the hub no longer runs its own OPA. A reference
  Rego bundle ships under `examples/opa-policies/`; the hub itself
  only consumes a Policy Engine via `POLICY_ENGINE_URL`.
- Hub network is now parameterizable (`HUB_NETWORK_NAME` /
  `HUB_NETWORK_EXTERNAL`) so the same compose works standalone or
  attached to an existing platform network.
- README rewritten around the 7-component logical architecture from
  the accompanying article. Vocabulary aligned: `Identity Provider`,
  `Artifact Store`, `Policy Engine` are roles, not products.
  Added "Policy Engine contract" section spelling out the HTTP wire
  format.

### Fixed

- nginx entrypoint race after a container restart: the wrapper used
  to seed `LAST_MTIME=0` and reload immediately on a flag that
  already existed on the shared volume, killing the freshly-booted
  master with exit 0. The watcher now seeds with the current mtime.
- Removed dead code: `build_search_index` + `full_index` in the
  Indexer (the search index is built server-side by the Filtering
  API), unused `Response` import, redundant `default.conf` removal.
- Aligned `SYNC_INTERVAL` Python default with the compose default
  (60 s; was 300 s but compose forced 60 anyway).
