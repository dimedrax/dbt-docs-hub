# dbt Docs Hub

[![CI](https://github.com/dimedrax/dbt-docs-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/dimedrax/dbt-docs-hub/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/deps-uv-261230)](https://docs.astral.sh/uv/)

Self-hosted, multi-project dbt documentation portal with column-level RBAC.

The hub is **tool-agnostic by design**: it stands on a 7-component logical
architecture, of which it ships **3 services** of its own and consumes
**3 platform components** through narrow contracts (any implementation
that honours the contract works). Pick what your platform already runs.

## Logical architecture (7 components)

| # | Component             | Contract                                                                                                                                | Default impl in this repo                   |
|---|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| 1 | **Identity Provider** | OIDC issuer producing a JWT with a `groups` claim                                                                                       | Keycloak                                    |
| 2 | **Policy Engine**     | HTTP endpoint that evaluates `{user, resource} → allow`. Policies live as code, in git, reviewed in PR                                  | OPA (Rego, package `dbtdocs`)               |
| 3 | **Filtering API**     | *(in this repo)* Receives the documentation request, consults the Policy Engine, returns only what the user is authorized to see       | `dbtdocs-filtering-api` (FastAPI)           |
| 4 | **Web Server**        | *(in this repo)* Serves static assets and routes requests                                                                               | `dbtdocs-web` (nginx)                       |
| 5 | **Metadata Indexer**  | *(in this repo)* Watches the Artifact Store, detects new projects, syncs documentation files, and reconfigures the Web Server on a loop | `dbtdocs-indexer` (Python)                  |
| 6 | **Artifact Store**    | S3-compatible bucket holding `<project>/manifest.json + catalog.json + index.html`                                                      | MinIO                                       |
| 7 | **Orchestrator**      | Triggers `dbt docs generate` and uploads to the Artifact Store                                                                          | *(out of scope here — Airflow / cron / CI)* |

The hub itself ships components 3, 4, 5 + an **OIDC edge proxy**
(`dbtdocs-oauth2-proxy`) that terminates the Identity Provider handshake
and forwards the JWT upstream. Components 1, 2, 6 are external — point
the env vars at any compliant implementation.

## Architecture

```
                +---------------+
   Browser ---> | OIDC edge     | --(OIDC)--> Identity Provider
                | proxy         |             (e.g. Keycloak)
                +-------+-------+
                        |
                        v
                +---------------+
                |  Web Server   |  static SPA shells
                +-------+-------+  + native dbt-docs HTML for the lineage iframe
                        |
            (proxy_pass for /api/* and /<project>/*.json)
                        |
                        v
                +---------------+
                | Filtering API | --(decision)--> Policy Engine
                +-------+-------+                 (e.g. OPA, package dbtdocs)
                        |
            (S3 client to fetch raw artefacts)
                        v
                +---------------+
                | Artifact Store|  bucket layout: <project>/
                +---------------+  (e.g. MinIO, AWS S3, GCS)

                +-------------------+
                |  Metadata Indexer |  every SYNC_INTERVAL seconds:
                +-------------------+   1. list project prefixes in the Artifact Store
                                        2. download into the web server volume
                                        3. re-render nginx.conf from the Jinja2
                                           template (one location block per project)
                                        4. touch a flag → web server reloads in-place
```

## Quickstart

The hub does not bundle Keycloak, MinIO, or OPA — you bring your own
stack. The checklist below assumes those three are already running on
a Docker network the hub can join.

### Prerequisites

- An **OIDC provider** reachable from the hub's network, with a client
  configured for `http://localhost:8095/oauth2/callback` and a JWT that
  carries a `groups` claim. Keycloak is the reference implementation.
- An **S3-compatible bucket** (e.g. MinIO, AWS S3) reachable from the
  hub's network, holding `<project>/manifest.json + catalog.json +
  index.html` for each dbt project you want to publish.
- A **Policy Engine** reachable from the hub's network, honouring the
  HTTP contract documented below (see "Policy Engine contract").
  `examples/opa-policies/` ships a working OPA bundle you can drop into
  your own OPA — start there or write your own.
- The hub will share a Docker network with these three services. Note
  the network name (e.g. `myplatform_default`).

### Bring the hub up

```bash
# 1. Configure
cp .env.example .env

# 1a. Generate the cookie secret (required)
SECRET=$(openssl rand -base64 32 | tr -- '+/' '-_' | tr -d '\n')
sed -i.bak "s|^OAUTH2_PROXY_COOKIE_SECRET=.*|OAUTH2_PROXY_COOKIE_SECRET=$SECRET|" .env && rm .env.bak

# 1b. Point the hub at YOUR services and YOUR Docker network. Edit .env:
#       KEYCLOAK_URL          → your OIDC issuer URL
#       MINIO_*               → your S3 endpoint + credentials + bucket
#       POLICY_ENGINE_URL     → your Policy Engine URL
#       HUB_NETWORK_NAME      → the Docker network of your platform
#       HUB_NETWORK_EXTERNAL  → true (so compose joins the existing network
#                                instead of creating a new one)

# 2. Up
docker compose --env-file .env up -d --build

# 3. Provision an OIDC client + groups in your IdP (Keycloak example)
KC_URL=http://your-keycloak:8080 KC_REALM=your-realm \
KC_ADMIN_USER=admin KEYCLOAK_ADMIN_PASSWORD=... \
  bash scripts/setup_keycloak_hub.sh

# 4. Smoke test (assumes 3 demo users + 3 groups exist in your IdP)
bash scripts/test_hub_e2e.sh
```

If your `KEYCLOAK_URL` uses a hostname (e.g. `keycloak.local`), make
sure it resolves on the host:

```bash
echo '127.0.0.1 keycloak.local' | sudo tee -a /etc/hosts
```

Then open <http://localhost:8095/> in a browser.

### Swapping any component

The defaults above are **one** valid wiring. To swap any of the three
external components, just repoint the env vars:

| Swap                  | What to do                                                                                                                              |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| **Identity Provider** | Point `KEYCLOAK_URL` / `KEYCLOAK_REALM` / `KEYCLOAK_CLIENT_*` at any OIDC issuer that emits a `groups` claim.                           |
| **Artifact Store**    | Point `MINIO_*` at any S3-compatible endpoint (AWS S3, GCS via interop, Ceph…).                                                         |
| **Policy Engine**     | Point `POLICY_ENGINE_URL` at any backend that honours the contract below. Start from `examples/opa-policies/` (working OPA bundle) or write your own.            |

The Filtering API only knows the contracts. Nothing in the hub assumes
"Keycloak", "MinIO", or "OPA" by name.

### Policy Engine contract

The hub speaks an HTTP wire format inspired by OPA's data API. Any
backend that honours it works:

```
POST {POLICY_ENGINE_URL}/v1/data/dbtdocs/allow
POST {POLICY_ENGINE_URL}/v1/data/dbtdocs/column_visible

Request:  {"input": {"user": {"groups": [...]},
                     "resource": {...}}}
Response: {"result": true | false}
```

Resource shape per decision:

| Decision          | `resource` fields                                           |
|-------------------|-------------------------------------------------------------|
| `allow`           | `{project}`                                                 |
| `column_visible`  | `{project, model, column, tags}` (`tags` may include `pii`) |

The hub fails **closed**: any non-200 response, network error, or
parsing failure defaults to deny. There is no fail-open knob — opening
access on infrastructure failure would defeat the purpose. If you don't
have a Policy Engine, the hub will refuse every request, by design.

## Reference RBAC groups

The hub doesn't ship users — it expects your IdP to do that. The Rego
bundle under `examples/opa-policies/` uses these group conventions
(which you can rename to fit your org):

| Group                 | Sees                                       | Sees PII |
|-----------------------|--------------------------------------------|----------|
| `dbt-docs-<project>`  | the `<project>` only                       | no       |
| `pii-authorized`      | (additive) PII-tagged columns where allowed | yes      |
| `dbt-docs-admin`      | every project                              | yes      |

Adapt to your IdP by editing `examples/opa-policies/policies/dbt-docs/project_access.rego`.

## Adding a new project

The hub auto-detects anything dropped under `<project>/` in the
Artifact Store. The Artifact Store layout per project is:

```
<bucket>/<project>/
├── manifest.json
├── catalog.json
└── index.html         # native dbt-docs SPA, used by the lineage iframe
```

Generate the three files with `dbt docs generate` and upload them to
the bucket (any S3 client works — `aws s3 cp`, `mc cp`, boto3 …). Then
create the matching IdP group `dbt-docs-<project>` and assign users to
it. The Metadata Indexer picks the project up at the next cycle
(default 60 s) — the home page and `nginx.conf` are regenerated
without restart.

## Repository layout

```
dbt-docs-hub/
├── docker-compose.yml          # 4 services: filtering-api, indexer, web, oauth2-proxy
├── .env.example                # environment template (copy to .env)
├── README.md
├── filtering_api/              # Filtering API (manifest, catalog, /api/*)
│   ├── main.py
│   ├── jwt_utils.py            # extract groups from the bearer token
│   ├── policy_engine.py        # httpx wrapper around the Policy Engine
│   ├── pyproject.toml          # deps managed by uv
│   ├── uv.lock                 # frozen transitive versions
│   └── Dockerfile
├── indexer/                    # Metadata Indexer — Artifact Store → web volume loop
│   ├── sync.py
│   ├── static/                 # SPA shells served as-is
│   │   ├── index.html          # home (React + react-router)
│   │   └── catalog.html        # per-project catalog (BrowserRouter SPA)
│   ├── templates/
│   │   └── nginx.conf.j2       # rendered every cycle into /etc/nginx/conf.d/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── Dockerfile
├── nginx/                      # Web Server config
│   ├── nginx.base.conf         # base config (loads conf.d/*.conf)
│   └── entrypoint.sh           # nginx + watcher that reloads on flag touch
├── scripts/
│   ├── setup_keycloak_hub.sh   # default-impl provisioning (Keycloak)
│   └── test_hub_e2e.sh         # E2E RBAC smoke tests
└── examples/
    ├── README.md
    └── opa-policies/           # reference Rego bundle for the Policy Engine
        ├── config.yaml
        └── policies/dbt-docs/  # package dbtdocs (allow + column_visible)
```

The Rego bundle under `examples/opa-policies/` is **documentation-as-code**,
not a runtime dependency. Drop it into your own OPA (or any other
Policy Engine that honours the HTTP contract) — see
[examples/README.md](examples/README.md).

Python deps for both services are managed with [`uv`](https://docs.astral.sh/uv/).
The Dockerfiles run `uv sync --frozen` against the committed `uv.lock`,
so production builds are byte-for-byte reproducible. For local edits:

```bash
cd dbt-docs-hub/filtering_api    # or indexer/
uv sync                          # creates .venv from uv.lock
uv add <package>                 # add a dep, refresh lockfile
uv run python -c "import main"   # run anything inside the env
```

## Environment variables

Defined in `docker-compose.yml`. All have defaults except the cookie
secret.

| Variable                     | Default                         | Notes                                            |
|------------------------------|---------------------------------|--------------------------------------------------|
| `OAUTH2_PROXY_COOKIE_SECRET` | _(none — required)_             | 32-byte url-safe base64                          |
| `MINIO_ENDPOINT`             | `http://minio:9000`             | Artifact Store — internal Docker URL             |
| `MINIO_ACCESS_KEY`           | `minio-admin`                   |                                                  |
| `MINIO_SECRET_KEY`           | `minio-secret-change-me`        |                                                  |
| `MINIO_BUCKET`               | `dbt-docs`                      |                                                  |
| `KEYCLOAK_URL`               | `http://keycloak.local:8090`    | Identity Provider — used for the OIDC issuer URL |
| `KEYCLOAK_REALM`             | `reborn`                        |                                                  |
| `KEYCLOAK_CLIENT_ID`         | `dbt-docs-hub`                  |                                                  |
| `KEYCLOAK_CLIENT_SECRET`     | `dbt-docs-hub-secret-change-me` |                                                  |
| `POLICY_ENGINE_URL`          | `http://opa:8181`               | Policy Engine — see contract below              |
| `SYNC_INTERVAL`              | `60`                            | Seconds between Metadata Indexer cycles          |
| `HUB_NETWORK_NAME`           | `dbt-docs-hub-net`              | Docker network name (override to join one)      |
| `HUB_NETWORK_EXTERNAL`       | `false`                         | Set `true` when joining an existing network     |

`MINIO_*` and `KEYCLOAK_*` variable names retain the defaults of the
reference implementations. They name a *role*, not a product —
repointing them at AWS S3, Auth0, or any other compatible endpoint
requires no code change. `POLICY_ENGINE_URL` is product-neutral by
construction.

## Debugging policy decisions

Hit the HTTP contract directly with `curl`:

```bash
# Project-level: a user in dbt-docs-voiture can see project voiture? (true)
curl -sX POST "$POLICY_ENGINE_URL/v1/data/dbtdocs/allow" \
  -d '{"input":{"user":{"groups":["dbt-docs-voiture"]},"resource":{"project":"voiture"}}}'

# Column-level: PII column visible to a non-pii-authorized user? (false)
curl -sX POST "$POLICY_ENGINE_URL/v1/data/dbtdocs/column_visible" \
  -d '{"input":{"user":{"groups":["dbt-docs-voiture"]},"resource":{"project":"voiture","tags":["pii"]}}}'
```

If you're using OPA with the bundled Rego, you can also evaluate
decisions in-process via `opa eval` inside your OPA container:

```bash
docker exec -i <your-opa-container> /opa eval --data /policies \
  --stdin-input --format=raw 'data.dbtdocs.allow' \
  <<<'{"user":{"groups":["dbt-docs-voiture"]},"resource":{"project":"voiture"}}'
```
