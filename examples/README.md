# Examples

Reference materials you can use to wire `dbt-docs-hub` to your own
platform. None of this is a runtime dependency of the hub itself — it's
documentation-as-code.

## `opa-policies/`

A working OPA bundle that satisfies the **Policy Engine contract**
documented in the root README (see "Policy Engine contract"). Drop it
into your own OPA deployment and point `POLICY_ENGINE_URL` at it.

```
opa-policies/
├── config.yaml                  # OPA bundle config (POC mode: file-based)
└── policies/
    └── dbt-docs/
        ├── main.rego            # package dbtdocs — entry point (allow + column_visible)
        ├── project_access.rego  # who can see which project
        └── column_access.rego   # column-level masking based on the `pii` tag
```

The package name `dbtdocs` is what the Filtering API queries
(`POST /v1/data/dbtdocs/allow` and `…/column_visible`). The bundled
group → project mapping is the one used in the ShopStream demo
personas; rewrite it to fit your own org's groups.

### Running OPA with this bundle

If you already run OPA, mount this directory:

```bash
docker run -d --name your-opa \
  -v "$(pwd)/opa-policies/policies:/policies:ro" \
  openpolicyagent/opa:1.7.1 \
  run --server --addr=0.0.0.0:8181 /policies
```

Then in `dbt-docs-hub/.env`:

```bash
POLICY_ENGINE_URL=http://your-opa:8181
```

### Writing your own Policy Engine

The hub doesn't care that you're using OPA. Anything that speaks the
HTTP contract works — see "Policy Engine contract" in the root README
for the wire format.
