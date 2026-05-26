#!/usr/bin/env bash
# Reborn DataOps Platform — provisioning of the dbt-docs hub in Keycloak.
# Idempotent: creates client + groups + assignments if they don't exist yet.
#
# Required env (with defaults):
#   KC_URL                       Keycloak base URL                http://localhost:8090
#   KC_REALM                     Target realm                     reborn
#   KC_ADMIN_USER                Admin user                       admin
#   KEYCLOAK_ADMIN_PASSWORD      Admin password                   admin-change-me
#   KEYCLOAK_CLIENT_SECRET       Secret to set on the new client  dbt-docs-hub-secret-change-me
#
# Optional, only used by the bundled Reborn demo where Keycloak's master
# realm refuses HTTP from localhost (sslRequired=external by default):
#   KC_CONTAINER                 docker container name to exec    (unset = skip the workaround)
set -euo pipefail

KC="${KC_URL:-http://localhost:8090}"
REALM="${KC_REALM:-reborn}"
ADMIN_USER="${KC_ADMIN_USER:-admin}"
ADMIN_PWD="${KEYCLOAK_ADMIN_PASSWORD:-admin-change-me}"

CLIENT_ID="dbt-docs-hub"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-dbt-docs-hub-secret-change-me}"

# Optional: relax sslRequired on master so the admin REST API answers HTTP
# on localhost. Only meaningful when Keycloak runs in a container we can
# exec into. Skipped silently otherwise — production setups won't need it.
KC_CONTAINER="${KC_CONTAINER:-}"
if [ -n "$KC_CONTAINER" ]; then
  echo "=== Relax sslRequired on master realm via $KC_CONTAINER (POC only) ==="
  docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master \
    --user "$ADMIN_USER" --password "$ADMIN_PWD" >/dev/null 2>&1 || true
  docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh update realms/master \
    -s sslRequired=NONE >/dev/null 2>&1 || true
fi

echo "=== Get admin token ==="
TOKEN=$(curl -sf -X POST "$KC/realms/master/protocol/openid-connect/token" \
  -d "username=$ADMIN_USER" -d "password=$ADMIN_PWD" \
  -d "grant_type=password" -d "client_id=admin-cli" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# ----- 1. Client -----
echo "=== Ensure client $CLIENT_ID exists ==="
EXISTING=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/clients?clientId=$CLIENT_ID" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")

if [ -z "$EXISTING" ]; then
  echo "  creating..."
  curl -sf -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "$KC/admin/realms/$REALM/clients" \
    -d "{
      \"clientId\": \"$CLIENT_ID\",
      \"enabled\": true,
      \"protocol\": \"openid-connect\",
      \"publicClient\": false,
      \"secret\": \"$CLIENT_SECRET\",
      \"directAccessGrantsEnabled\": true,
      \"standardFlowEnabled\": true,
      \"serviceAccountsEnabled\": false,
      \"redirectUris\": [
        \"http://localhost:8090/oauth2/callback\",
        \"http://localhost/oauth2/callback\"
      ],
      \"webOrigins\": [\"+\"]
    }"
  EXISTING=$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "$KC/admin/realms/$REALM/clients?clientId=$CLIENT_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
fi
echo "  client uuid: $EXISTING"

echo "=== Reset client secret + post-logout URIs ==="
curl -sf -o /dev/null -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$KC/admin/realms/$REALM/clients/$EXISTING" \
  -d "{
    \"secret\": \"$CLIENT_SECRET\",
    \"attributes\": {
      \"post.logout.redirect.uris\": \"http://localhost:8095/##http://localhost:8095/oauth2/sign_out\"
    }
  }"

# ----- 2. Groups mapper on client (so groups claim is in the JWT) -----
echo "=== Ensure groups protocol mapper on client ==="
MAPPERS=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/clients/$EXISTING/protocol-mappers/models")
HAS=$(echo "$MAPPERS" | python3 -c "
import sys, json
m = json.load(sys.stdin)
print('yes' if any(x.get('name')=='groups' for x in m) else 'no')")

if [ "$HAS" = "no" ]; then
  curl -sf -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "$KC/admin/realms/$REALM/clients/$EXISTING/protocol-mappers/models" \
    -d '{
      "name": "groups",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-group-membership-mapper",
      "config": {
        "claim.name": "groups",
        "full.path": "false",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true"
      }
    }'
  echo "  groups mapper added"
else
  echo "  groups mapper already present"
fi

# ----- 3. Groups -----
ensure_group() {
  local name=$1
  local existing
  existing=$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "$KC/admin/realms/$REALM/groups?search=$name" \
    | python3 -c "
import sys, json
name = '$name'
print(next((g['id'] for g in json.load(sys.stdin) if g['name']==name), ''))")
  if [ -z "$existing" ]; then
    curl -sf -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      "$KC/admin/realms/$REALM/groups" \
      -d "{\"name\": \"$name\"}"
    existing=$(curl -sf -H "Authorization: Bearer $TOKEN" \
      "$KC/admin/realms/$REALM/groups?search=$name" \
      | python3 -c "
import sys, json
name = '$name'
print(next((g['id'] for g in json.load(sys.stdin) if g['name']==name), ''))")
    echo "  group $name created ($existing)"
  else
    echo "  group $name already exists ($existing)"
  fi
  echo "$existing"
}

echo "=== Ensure groups ==="
G_VOITURE=$(ensure_group "dbt-docs-voiture" | tail -1)
G_PII=$(ensure_group "pii-authorized" | tail -1)
G_ADMIN=$(ensure_group "dbt-docs-admin" | tail -1)

# ----- 4. Users -> groups -----
user_id() {
  curl -sf -H "Authorization: Bearer $TOKEN" \
    "$KC/admin/realms/$REALM/users?username=$1" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')"
}

assign() {
  local user=$1
  local gid=$2
  local label=$3
  local uid
  uid=$(user_id "$user")
  if [ -z "$uid" ]; then
    echo "  user $user not found in keycloak — skipping"
    return
  fi
  curl -sf -o /dev/null -X PUT -H "Authorization: Bearer $TOKEN" \
    "$KC/admin/realms/$REALM/users/$uid/groups/$gid" || true
  echo "  $user → $label"
}

echo "=== Assign LDAP users to hub groups ==="
# Alice = voiture reader (no PII)
assign alice "$G_VOITURE" "dbt-docs-voiture"
# Charlie = admin (sees every project + every PII column)
assign charlie "$G_ADMIN" "dbt-docs-admin"

echo ""
echo "===================================================================="
echo "Keycloak hub provisioning complete."
echo "    Client      : $CLIENT_ID"
echo "    Groups      : dbt-docs-voiture, pii-authorized, dbt-docs-admin"
echo "    Assignments : alice -> voiture, charlie -> admin"
echo "===================================================================="
