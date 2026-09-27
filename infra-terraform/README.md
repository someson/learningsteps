# Infrastructure as Code (Terraform)

Provisions the whole LearningSteps environment: network, AKS, PostgreSQL
Flexible Server, Container Registry, Key Vault, and the two managed identities
that later phases authenticate with.

## Prerequisites

- Terraform >= 1.9
- Azure CLI, logged in (`az login`) with an active subscription
- Permission to create role assignments (`Owner`, or `User Access
  Administrator` plus `Contributor`). `Contributor` alone is **not** enough —
  the `azurerm_role_assignment` resources here will fail without it.

- kubelogin (`brew install Azure/kubelogin/kubelogin`) — the cluster has
  local accounts disabled, so kubectl authenticates through Entra ID

## Run order

```bash
# 0. Variables, shared by both configurations
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars          # github_repository, admin_ip_ranges

# 1. State backend (once, ever). Uses local state for itself.
cd bootstrap
terraform init
terraform apply -var-file=../terraform.tfvars
terraform output -raw backend_hcl > ../backend.hcl

# 2. Main configuration
cd ..
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

`admin_ip_ranges` must contain the public IP of the machine running
Terraform. Key Vault, the state storage account and the AKS API server all
refuse everyone else. If your ISP hands you a new IP, update the file and
re-apply both configurations; a 403 from Key Vault or storage is the symptom.

First apply takes roughly 15–20 minutes; AKS and PostgreSQL dominate that.

If `terraform init` fails with a 403 on the storage account, the
`Storage Blob Data Contributor` assignment from bootstrap has not propagated
yet. Wait a minute and retry.

## What gets built

| Resource | Purpose |
|---|---|
| VNET + 2 subnets | `snet-aks` for nodes (Key Vault service endpoint), `snet-db` delegated to PostgreSQL |
| Private DNS zone | Makes the database FQDN resolvable inside the VNET only |
| PostgreSQL Flexible Server | VNET-integrated, no public endpoint |
| AKS | Entra ID + Azure RBAC, no local accounts, API limited to admin IPs, Workload Identity, Key Vault CSI driver, Calico policy, auto patch upgrades |
| Static public IP | Ingress address for Caddy; Let's Encrypt issues the certificate for it |
| ACR | Standard tier, admin account disabled |
| Key Vault | RBAC mode, network-restricted, holds `database-url` and `database-admin-url` |
| `workload` identity | Assumed by API pods; reads `database-url` only |
| `migrator` identity | Assumed by the schema Job; reads both secrets |
| `github` identity | Assumed by CI; pushes images, deploys to one namespace |

## Design notes

**No secrets in CI, anywhere.** Both identities use OIDC federation rather
than client secrets. GitHub Actions presents a token whose subject is
`repo:<owner>/<name>:ref:refs/heads/main`; Entra ID accepts it only for that
exact repo and branch. A fork or a feature branch produces a different subject
and is refused, so deployment rights cannot be obtained by opening a pull
request. Pods likewise present a token whose subject is
`system:serviceaccount:<namespace>:<name>` — a pod using any other
ServiceAccount gets nothing.

**Database isolation is structural, not filtered.** In the VM build, three
independent layers (NSG, `pg_hba.conf`, `ufw`) each had to be configured to
keep Postgres private. Here the Flexible Server runs in private-access mode:
it has no public endpoint at all and resolves only through a private DNS zone
linked to this VNET. The NSG rules on `snet-db` are defence in depth rather
than the primary control. Note that private access is fixed at creation —
a server cannot later be switched to public access, or back.

**CNI overlay, deliberately.** Pods draw addresses from `10.244.0.0/16`
instead of the VNET. With standard Azure CNI, every pod consumes a real VNET
address and the `/22` node subnet would be exhausted by a few dozen pods.

**Passwords never touch state.** Both Postgres passwords are
`ephemeral "random_password"` values passed to write-only arguments
(`administrator_password_wo`, `value_wo`). One apply feeds the same value to
the server and to Key Vault; neither the plan nor the state records it. To
rotate, bump `postgres_password_version` and re-run the migration Job so it
resets the app role's password.

**The app does not connect as admin.** Terraform cannot reach a private
server to create roles, so a Kubernetes Job (identity `migrator`) reads the
admin DSN, creates the `learningsteps` role with the password from
`database-url`, and applies the schema. API pods can read only
`database-url`; the secret-level role assignments keep the admin DSN out of
their reach even though both secrets share a vault.

**Kubernetes access goes through Entra ID.** Without
`azure_rbac_enabled`, the namespace-scoped `RBAC Writer` role would be
decorative and `Cluster User Role` would hand CI a certificate that is
effectively cluster-admin. Local accounts are disabled, so there is no static
admin credential to leak. Whoever runs Terraform gets `RBAC Cluster Admin`.

**Least privilege on the CI identity.** `AcrPush` on the registry, plus
`Cluster User` (which only fetches a kubeconfig) and `RBAC Writer` scoped to
the single application namespace. Not `Cluster Admin`, which would also permit
cluster-wide RBAC changes and node access. There is no federated credential
for `pull_request` events: PR jobs build and scan without Azure access, so a
PR branch cannot push images or deploy.

**Purge protection is off** on the Key Vault so `terraform destroy` followed
by `terraform apply` genuinely round-trips — one of the project's success
criteria. With purge protection on, the vault name stays reserved for 90 days
and the second apply fails. Turn it on for anything real.

## Known state-file consideration

The state holds no passwords (see above), but it is still sensitive: it maps
every resource ID, IP and identity. The backend storage account has shared
keys disabled, blob versioning on, network access limited to
`admin_ip_ranges`, and access through Entra ID identities only. Never move
this state to a local file or commit it.

## Outputs you will need later

```bash
terraform output aks_get_credentials_command     # phase 3
terraform output workload_identity_client_id     # phase 3, API ServiceAccount annotation
terraform output migrator_identity_client_id     # phase 3, migration Job ServiceAccount
terraform output ingress_public_ip               # phase 3, Caddy Service + Caddyfile
terraform output github_repository_variables     # phase 4, repo variables
```

## Teardown

```bash
terraform destroy
```

The bootstrap resource group is separate and survives, so state storage
persists between teardowns. Per the project brief, do **not** destroy this
environment when finished — a later project reuses it.
