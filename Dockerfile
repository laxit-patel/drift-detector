# Change Monitor — stateless compute image.
# All persistent state (kb, findings, reports) lives under /work/state, which
# the CI workflow restores from git before the run and commits back after.
# Secrets arrive via env at run time — none are baked into the image.
FROM python:3.12-slim AS base

# Runtime deps only (no pytest). Kept in a separate layer for cache reuse.
COPY requirements.txt /tmp/requirements.txt
RUN grep -v '^pytest' /tmp/requirements.txt > /tmp/runtime-requirements.txt \
    && pip install --no-cache-dir -r /tmp/runtime-requirements.txt \
    && rm -f /tmp/requirements.txt /tmp/runtime-requirements.txt

WORKDIR /work

# Application code + the default production config (override by mounting your own).
COPY agent/ /work/agent/
COPY deploy/config.yaml /work/config.yaml
COPY docker/run-monitor.sh /work/run-monitor.sh
RUN chmod +x /work/run-monitor.sh

# Run as an unprivileged user; /work/state is a mount point owned by it.
RUN useradd --create-home --uid 10001 monitor \
    && mkdir -p /work/state \
    && chown -R monitor:monitor /work
USER monitor

# The container is stateless: it reads/writes /work/state and exits.
ENTRYPOINT ["/work/run-monitor.sh"]
