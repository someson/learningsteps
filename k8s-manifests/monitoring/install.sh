#!/usr/bin/env bash
# Installs or updates monitoring in AKS: kube-prometheus-stack (Prometheus,
# Grafana, operator), the LearningSteps PodMonitor, alert rules and dashboard.
# Run by the operator (cluster-scoped objects; CI cannot), from any directory:
#
#   k8s-manifests/monitoring/install.sh
#   k8s-manifests/monitoring/port-forward.sh     # Grafana :3000, Prometheus :9090
#   kubectl get secret -n monitoring grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d
#
# Idempotent. The dashboard and rules are the same files the local compose
# stack uses (monitoring/ in the repo root).
set -euo pipefail
cd "$(dirname "$0")"
ROOT=../..

CHART=oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack
# Pinned; bump deliberately (helm show chart $CHART --version <new>).
CHART_VERSION=91.8.2
RELEASE=kube-prometheus-stack
NS=monitoring

kubectl apply -f namespace.yaml

# Grafana admin password: random, generated once, never in git or values.
if ! kubectl get secret -n "$NS" grafana-admin >/dev/null 2>&1; then
  kubectl create secret generic grafana-admin -n "$NS" \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="$(openssl rand -base64 24)"
fi

helm upgrade --install "$RELEASE" "$CHART" --version "$CHART_VERSION" \
  --namespace "$NS" -f values.yaml --wait --timeout 10m

kubectl apply -f networkpolicies.yaml

# Needs the CRDs installed by the chart above.
kubectl apply -f podmonitor.yaml
{
  cat <<'YAML'
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: learningsteps
  namespace: learningsteps
spec:
YAML
  sed 's/^/  /' "$ROOT/monitoring/prometheus/rules.yml"
} | kubectl apply -f -

kubectl create configmap learningsteps-dashboard -n "$NS" \
  --from-file=learningsteps.json="$ROOT/monitoring/grafana/dashboards/learningsteps.json" \
  --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml \
  | kubectl annotate --local -f - grafana_folder=LearningSteps -o yaml \
  | kubectl apply -f -

kubectl rollout status -n "$NS" deploy/"$RELEASE"-grafana --timeout=180s

# Every running pod must pass Pod Security "restricted" (the namespace
# enforces it for new pods). Warnings below name pods that would not.
echo "Pod Security check (restricted):"
kubectl label --dry-run=server --overwrite ns "$NS" pod-security.kubernetes.io/enforce=restricted

echo
echo "Grafana + Prometheus on localhost:3000 / :9090 (one terminal, reconnects):"
echo "  k8s-manifests/monitoring/port-forward.sh"
echo "  or in the background: overmind start -f k8s-manifests/monitoring/Procfile -r all -D"
echo "Password: kubectl get secret -n $NS grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d"
