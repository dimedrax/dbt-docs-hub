#!/usr/bin/env bash
# Reborn DataOps Platform — dbt-docs hub E2E test suite.
#
# Walks through the 8 RBAC scenarios documented in the README and checks
# the HTTP response codes + the columns FastAPI returns. The script does
# not fail hard on individual assertions (use grep for FAIL markers in CI),
# but prints a summary line so you can scan the output quickly.
set -uo pipefail

PORTAL="${PORTAL_URL:-http://localhost:8095}"
KC="${KC_URL:-http://localhost:8090}"
REALM="${KEYCLOAK_REALM:-reborn}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID:-dbt-docs-hub}"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-dbt-docs-hub-secret-change-me}"
OPA_CONTAINER="${OPA_CONTAINER:-opa}"
PROJECT="${TEST_PROJECT:-voiture}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $*"; }
ko()   { FAIL=$((FAIL+1)); echo "  ✗ $*"; }
hr()   { echo ""; echo "──── $* ────"; }

get_token() {
    curl -sf -X POST "$KC/realms/$REALM/protocol/openid-connect/token" \
        -d "username=$1" -d "password=$2" \
        -d "grant_type=password" -d "client_id=$CLIENT_ID" \
        -d "client_secret=$CLIENT_SECRET" -d "scope=openid" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

list_columns() {
    python3 -c "
import json, sys
m = json.load(sys.stdin)
nodes = m.get('nodes', {})
for k, n in sorted(nodes.items()):
    cols = sorted((n.get('columns') or {}).keys())
    print(f'      {n.get(\"name\",\"?\")}: {cols}')
"
}

ALICE=$(get_token alice alice-demo-pwd)
CHARLIE=$(get_token charlie charlie-demo-pwd)
BOB=$(get_token bob bob-demo-pwd)

# ────────────────────────────────────────────────────────────────────────────
hr "1. Hub health endpoint (no auth)"
code=$(curl -s -o /dev/null -w "%{http_code}" "$PORTAL/health")
[ "$code" = "200" ] && ok "/health -> 200" || ko "/health -> $code"

# ────────────────────────────────────────────────────────────────────────────
hr "2. Anonymous request must be redirected to Keycloak"
code=$(curl -s -o /dev/null -w "%{http_code}" "$PORTAL/")
[ "$code" = "302" ] && ok "/ -> 302 (redirect to Keycloak)" || ko "/ -> $code"

# ────────────────────────────────────────────────────────────────────────────
hr "3. Alice (dbt-docs-$PROJECT, NOT pii-authorized) on /api/$PROJECT/models"
code=$(curl -s -o /tmp/alice_models -w "%{http_code}" -H "Authorization: Bearer $ALICE" "$PORTAL/api/$PROJECT/models")
if [ "$code" = "200" ]; then
    n=$(python3 -c "import json; print(len(json.load(open('/tmp/alice_models'))['models']))")
    ok "/api/$PROJECT/models -> 200 ($n models visible)"
else
    ko "/api/$PROJECT/models -> $code (expected 200)"
fi

# ────────────────────────────────────────────────────────────────────────────
hr "4. Alice on /$PROJECT/manifest.json — PII columns must be stripped"
curl -s -H "Authorization: Bearer $ALICE" "$PORTAL/$PROJECT/manifest.json" -o /tmp/alice_manifest
HIDDEN=$(python3 -c "
import json
m = json.load(open('/tmp/alice_manifest'))
n = m.get('nodes', {}).get('model.$PROJECT.dim_client', {})
cols = set((n.get('columns') or {}).keys())
forbidden = {'nom','prenom','email','telephone','date_naissance','adresse'}
leaked = cols & forbidden
print(','.join(sorted(leaked)) if leaked else 'none')
")
[ "$HIDDEN" = "none" ] && ok "no PII column leaked to Alice" || ko "PII columns leaked to Alice: $HIDDEN"
echo "    Visible columns:"
cat /tmp/alice_manifest | list_columns

# ────────────────────────────────────────────────────────────────────────────
hr "5. Bob (no hub group) on /api/$PROJECT/models — must be denied"
code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $BOB" "$PORTAL/api/$PROJECT/models")
[ "$code" = "403" ] && ok "/api/$PROJECT/models -> 403 for Bob" || ko "/api/$PROJECT/models -> $code for Bob (expected 403)"

# ────────────────────────────────────────────────────────────────────────────
hr "6. Charlie (dbt-docs-admin) on /$PROJECT/manifest.json — every PII column visible"
curl -s -H "Authorization: Bearer $CHARLIE" "$PORTAL/$PROJECT/manifest.json" -o /tmp/charlie_manifest
HAS_PII=$(python3 -c "
import json
m = json.load(open('/tmp/charlie_manifest'))
n = m.get('nodes', {}).get('model.$PROJECT.dim_client', {})
cols = set((n.get('columns') or {}).keys())
required = {'nom','prenom','email','telephone'}
missing = required - cols
print(','.join(sorted(missing)) if missing else 'all-present')
")
[ "$HAS_PII" = "all-present" ] && ok "Charlie sees every PII column" || ko "Charlie missing PII columns: $HAS_PII"

# ────────────────────────────────────────────────────────────────────────────
hr "7. Direct OPA decisions (via 'opa eval' inside the OPA container)"
opa_eval() {
    # $1 = JSON for OPA `input`. Returns 'true' / 'false'.
    docker exec -i "$OPA_CONTAINER" /opa eval --data /policies \
        --stdin-input --format=raw 'data.dbtdocs.allow' <<<"$1" 2>/dev/null
}

RESULT=$(opa_eval "{\"user\":{\"groups\":[\"dbt-docs-$PROJECT\"]},\"resource\":{\"project\":\"$PROJECT\"}}")
[ "$RESULT" = "true" ] && ok "OPA: dbt-docs-$PROJECT can access $PROJECT" || ko "OPA: unexpected result '$RESULT'"

RESULT=$(opa_eval "{\"user\":{\"groups\":[\"random-group\"]},\"resource\":{\"project\":\"$PROJECT\"}}")
[ "$RESULT" = "false" ] && ok "OPA: random user denied" || ko "OPA: unexpected result '$RESULT'"

# ────────────────────────────────────────────────────────────────────────────
hr "8. Home page lists $PROJECT for Charlie"
curl -s -H "Authorization: Bearer $CHARLIE" "$PORTAL/api/projects" -o /tmp/projects
PROJS=$(python3 -c "import json; print(','.join(p['name'] for p in json.load(open('/tmp/projects'))['projects']))")
echo "    /api/projects → [$PROJS]"
echo "$PROJS" | grep -q "$PROJECT" && ok "$PROJECT visible on home" || ko "$PROJECT missing from home"

# ────────────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  Summary: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════════════════════"
[ $FAIL -eq 0 ] || exit 1
