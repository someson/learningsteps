#!/usr/bin/env bash
# Grafana and Prometheus from AKS on localhost, from one terminal:
#
#   k8s-manifests/monitoring/port-forward.sh
#   → Grafana http://localhost:3000, Prometheus http://localhost:9090
#   Ctrl+C stops both.
#
# `kubectl port-forward` exits whenever its pod restarts (rollout,
# install.sh, OOM); each forward here reconnects by itself. Bound to
# 127.0.0.1 only. Ports can be changed: GRAFANA_PORT=3001 ./port-forward.sh
# Works with the bash 3.2 that ships with macOS.
set -uo pipefail

NS=monitoring
RELEASE=kube-prometheus-stack
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

kubectl get ns "$NS" >/dev/null || { echo "No access to namespace $NS (kubectl context: $(kubectl config current-context 2>/dev/null))" >&2; exit 1; }

# forward <name> <service> <local port> <service port>
forward() {
  while true; do
    # Last line kubectl printed says why it stopped (pod restarted, port
    # already in use, credentials expired).
    reason="$(kubectl port-forward -n "$NS" --address 127.0.0.1 "svc/$2" "$3:$4" 2>&1 | tail -1)"
    echo "$(date +%H:%M:%S) $1 stopped: ${reason:-no output} — reconnecting in 3 s"
    sleep 3
  done
}

# Ctrl+C or exit: stop the whole process group — both loops and the
# kubectl processes they started.
trap 'trap - INT TERM EXIT; echo; echo "Stopping port-forwards"; kill 0 2>/dev/null' INT TERM EXIT

forward Grafana "$RELEASE-grafana" "$GRAFANA_PORT" 80 &
forward Prometheus "$RELEASE-prometheus" "$PROMETHEUS_PORT" 9090 &

echo "Grafana:    http://localhost:$GRAFANA_PORT  (user admin)"
echo "Prometheus: http://localhost:$PROMETHEUS_PORT"
echo "Password → clipboard (macOS): kubectl get secret -n $NS grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d | pbcopy"
echo "Ctrl+C to stop."
wait
