#!/usr/bin/env bash
# Renders cluster/ and app/ into rendered/ by substituting ${VAR} placeholders.
#
# Every value can come from the environment (CI sets them from repository
# variables). Anything unset is read from `terraform output`, which works
# locally for the operator who ran Terraform.
#
#   ACME_EMAIL=you@example.com ./render.sh
#   kubectl apply -f rendered/cluster/          # operator, once
#   kubectl apply -f rendered/app/              # every deploy
set -euo pipefail
cd "$(dirname "$0")"

TF_DIR="${TF_DIR:-../infra-terraform}"
tf() { terraform -chdir="$TF_DIR" output -raw "$1"; }

: "${ACME_EMAIL:?Set ACME_EMAIL to the ACME account e-mail}"
# Commit SHA; "-dirty" marks an image built from uncommitted changes.
if [ -z "${IMAGE_TAG:-}" ]; then
  IMAGE_TAG="$(git rev-parse --short HEAD)"
  git diff-index --quiet HEAD -- || IMAGE_TAG="${IMAGE_TAG}-dirty"
fi
: "${CADDY_IMAGE_TAG:=$IMAGE_TAG}"

: "${ACR_LOGIN_SERVER:=$(tf acr_login_server)}"
: "${WORKLOAD_CLIENT_ID:=$(tf workload_identity_client_id)}"
: "${MIGRATOR_CLIENT_ID:=$(tf migrator_identity_client_id)}"
: "${TENANT_ID:=$(tf tenant_id)}"
: "${KEY_VAULT_NAME:=$(tf key_vault_name)}"
: "${INGRESS_IP:=$(tf ingress_public_ip)}"
: "${INGRESS_PIP_NAME:=$(tf ingress_public_ip_name)}"
: "${INGRESS_RG:=$(tf ingress_resource_group)}"
: "${DB_SUBNET_CIDR:=$(tf db_subnet_cidr)}"
: "${ENTRA_CLIENT_ID:=$(tf entra_client_id)}"
: "${ENTRA_TENANT:=$(tf entra_authority_tenant)}"
: "${ENTRA_ALLOWED_TENANTS:=$(tf entra_allowed_tenants)}"

API_IMAGE="${ACR_LOGIN_SERVER}/learningsteps-api:${IMAGE_TAG}"
CADDY_IMAGE="${ACR_LOGIN_SERVER}/learningsteps-caddy:${CADDY_IMAGE_TAG}"
# Rolls the Caddy pod when anything that ends up in the Caddyfile changes.
CADDYFILE_SHA="$(printf '%s\n' "$(cat app/caddy.yaml)" "$INGRESS_IP" "$ACME_EMAIL" | shasum -a 256 | cut -c1-16)"

export IMAGE_TAG API_IMAGE CADDY_IMAGE CADDYFILE_SHA WORKLOAD_CLIENT_ID MIGRATOR_CLIENT_ID \
       TENANT_ID KEY_VAULT_NAME INGRESS_IP INGRESS_PIP_NAME INGRESS_RG DB_SUBNET_CIDR ACME_EMAIL \
       ENTRA_CLIENT_ID ENTRA_TENANT ENTRA_ALLOWED_TENANTS

# Explicit list: only these placeholders are replaced, anything else that
# looks like $VAR is left alone.
VARS='${IMAGE_TAG} ${API_IMAGE} ${CADDY_IMAGE} ${CADDYFILE_SHA} ${WORKLOAD_CLIENT_ID} ${MIGRATOR_CLIENT_ID} ${TENANT_ID} ${KEY_VAULT_NAME} ${INGRESS_IP} ${INGRESS_PIP_NAME} ${INGRESS_RG} ${DB_SUBNET_CIDR} ${ACME_EMAIL} ${ENTRA_CLIENT_ID} ${ENTRA_TENANT} ${ENTRA_ALLOWED_TENANTS}'

rm -rf rendered
for dir in cluster app; do
  mkdir -p "rendered/$dir"
  for f in "$dir"/*.yaml; do
    envsubst "$VARS" < "$f" > "rendered/$f"
  done
done

if grep -rn '\${[A-Z_]*}' rendered/; then
  echo "error: unrendered placeholders above" >&2
  exit 1
fi
echo "Rendered to $(pwd)/rendered (image tag ${IMAGE_TAG})"
