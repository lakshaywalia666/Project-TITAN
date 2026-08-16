ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="Project Titan" \
      org.opencontainers.image.description="Zero-cost-first AI-native control plane" \
      org.opencontainers.image.version="0.1.0"

ARG TITAN_UID=10001
ARG TITAN_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/titan/src

RUN groupadd --gid "${TITAN_GID}" titan \
    && useradd --uid "${TITAN_UID}" --gid titan --no-create-home --shell /usr/sbin/nologin titan \
    && mkdir -p /opt/titan /var/lib/titan \
    && chown -R titan:titan /opt/titan /var/lib/titan

WORKDIR /opt/titan
COPY --chown=titan:titan src ./src
COPY --chown=titan:titan VERSION ./VERSION

USER titan:titan

EXPOSE 8080 8090 8100 8200 8300

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2).read()"]

CMD ["python", "-m", "titan_control.api_main"]
