# Contributing

Thanks for considering a contribution. The hub is small enough that
most changes can land in one PR; please keep them focused.

## Dev setup

The hub has two Python services, each with its own [`uv`](https://docs.astral.sh/uv/)
project. Pick the one you're touching and `uv sync`:

```bash
cd dbt-docs-hub/filtering_api    # or indexer/
uv sync                          # creates .venv from uv.lock + dev deps
```

## Before opening a PR

Run the same checks CI runs:

```bash
# In the service directory you changed:
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For changes that touch routing, JWT handling, the Policy Engine wire
format, the Metadata Indexer's nginx template, or the docker-compose
wiring, also run the end-to-end suite against a live stack. You'll
need your own Keycloak, MinIO, and OPA reachable (see the README
Quickstart):

```bash
docker compose --env-file .env up -d --build
KC_CONTAINER=<your-keycloak-container> bash scripts/setup_keycloak_hub.sh
bash scripts/test_hub_e2e.sh   # must stay 9/9
```

## What goes where

| Change                              | Files to edit                                                        |
|-------------------------------------|----------------------------------------------------------------------|
| New API endpoint                    | `filtering_api/main.py` + tests + `indexer/templates/nginx.conf.j2`  |
| New JWT claim handling              | `filtering_api/jwt_utils.py` + tests                                 |
| Policy Engine contract change       | `filtering_api/policy_engine.py` + README "Policy Engine contract" + reference Rego under `examples/opa-policies/` |
| New external dependency             | `<service>/pyproject.toml` then `uv lock`                            |
| New env var                         | `docker-compose.yml` + `.env.example` + README "Environment variables" |
| New service                         | top-level dir + `docker-compose.yml` + README "Logical architecture" |

## Commit conventions

Conventional commits style is appreciated but not enforced
(`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).

Keep commit messages descriptive about the *why* — the diff already
shows the *what*.

## Reporting bugs

Use GitHub Issues for non-security bugs. For anything security-related,
read [SECURITY.md](SECURITY.md) first.
