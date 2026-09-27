# syntax=docker/dockerfile:1

# Chainguard Python: no shell, no package manager, 0 known CVEs at the time of
# pinning (python:3.12-slim had 44 unfixed HIGH in Debian packages). The free
# tier publishes only `latest`, so both images are pinned by digest — the
# Python version changes only when these digests are bumped deliberately
# (Dependabot), and fixes arrive only through such a bump.
#
# builder: latest-dev = same Python plus shell and pip, used only to build.

# --- Build stage: dependencies into an isolated venv ------------------------
FROM cgr.dev/chainguard/python:latest-dev@sha256:87729167739190d9309588120a8ac0ffbf2eb95dd895abb9bada6bb9ecbf5a04 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY api/requirements.txt /tmp/requirements.txt
# pip is not needed at runtime, and its vendored msgpack/setuptools carry
# HIGH CVEs of their own. Remove it from the venv that ships.
RUN pip install -r /tmp/requirements.txt \
 && pip uninstall -y pip

# --- Runtime stage ----------------------------------------------------------
FROM cgr.dev/chainguard/python:latest@sha256:be59f7abb600892c78e6ff0fe1a8f39549da13302dc003c8a5eb1c14b03d995c

# HOME must point at a directory that exists and is readable. asyncpg probes
# ~/.postgresql/postgresql.key on every connect; if HOME is unreadable the
# probe raises EACCES instead of "not found" and every request returns 500
# (the ProtectHome lesson from the VM deployment). /home/nonroot exists in
# this image; stated explicitly so the dependency is visible.
ENV PATH="/app/venv/bin:$PATH" \
    HOME=/home/nonroot \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /app/venv /app/venv

# Code is owned by root and only readable by the app user: a compromised
# process cannot modify what it runs. Works with readOnlyRootFilesystem.
COPY api/ /app/api/

WORKDIR /app/api

# Chainguard's built-in non-root user. Numeric, so Kubernetes can verify
# runAsNonRoot without a passwd lookup.
USER 65532:65532

EXPOSE 8000

# Exec form: there is no shell in this image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# No --reload: that is a development flag. 0.0.0.0 is correct inside a
# container — exposure is decided by the published port / Kubernetes Service.
ENTRYPOINT ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
