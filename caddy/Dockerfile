# syntax=docker/dockerfile:1

# Caddy ingress for LearningSteps: TLS termination with a Let's Encrypt
# certificate for the bare public IP, reverse proxy to the API Service.
#
# Built from source (main.go + go.mod) rather than using the official image,
# whose bundled Go dependencies carried 17 fixable HIGH CVEs. The runtime is
# Chainguard static: no shell, no package manager, CA certificates included
# (needed for ACME), non-root user 65532.

# --- Build stage ------------------------------------------------------------
FROM golang:alpine@sha256:8a5910f31396cd4d89662f56c68b3ae31d374308270a1c3bd96672ee5ed43414 AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./

# Static binary: the runtime image has no libc.
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/caddy .

# --- Runtime stage ----------------------------------------------------------
FROM cgr.dev/chainguard/static:latest@sha256:41e17ed83c594a64a9396b6ab96dd26d5ddc290dacf4c177464712ff21ad534f

COPY --from=build /out/caddy /usr/bin/caddy

# Certificates and the ACME account live in XDG_DATA_HOME, which must be a
# persistent volume in Kubernetes (otherwise every restart re-issues and hits
# Let's Encrypt rate limits). XDG_CONFIG_HOME holds autosaved config only.
ENV XDG_DATA_HOME=/data \
    XDG_CONFIG_HOME=/config

USER 65532:65532

# Unprivileged ports: the Kubernetes Service maps 80→8080 and 443→8443, so
# Caddy never needs root or NET_BIND_SERVICE.
EXPOSE 8080 8443

ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
