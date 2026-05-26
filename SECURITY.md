# Security Policy

The dbt Docs Hub is an RBAC enforcement layer. Bugs here can leak data
that the Policy Engine intended to deny. Please report findings through
the channel below before disclosing publicly.

## Reporting a vulnerability

Email **dimedrax@gmail.com** with:

- A clear description of the issue and the impact (data exposure,
  privilege escalation, denial of service…).
- Steps to reproduce, ideally against the demo stack in this repo.
- Affected version (commit SHA).

You will get an acknowledgement within **5 business days** and an
initial assessment within **10 business days**.

Please do **not** open public GitHub issues or pull requests for
security-sensitive bugs.

## Scope

In scope:

- The Filtering API (authorization bypass, claim spoofing, response
  leakage of denied projects/columns).
- The OIDC edge proxy configuration shipped here.
- The Metadata Indexer (path traversal during MinIO sync, arbitrary
  file write into the web volume).
- The default `dbtdocs` Rego bundle (logic errors granting unintended
  access).

Out of scope:

- Vulnerabilities in upstream dependencies (Keycloak, OPA, MinIO,
  oauth2-proxy, nginx, FastAPI, boto3, jinja2, …) — please report
  those to the respective projects.
- Misconfigurations in *your* deployment (e.g. running with
  `OAUTH2_PROXY_COOKIE_SECRET=changeme`).
- Issues that require an attacker who already has valid credentials
  for a privileged group.

## Security model

The hub fails **closed**. If the Policy Engine is unreachable, every
decision defaults to deny. There is no fail-open knob. Reports of
"the hub denied my request when OPA was down" are working as intended.
