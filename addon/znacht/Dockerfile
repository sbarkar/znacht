# HA add-on wrapper around the same engine image. The Supervisor builds it with this folder as context.
ARG BUILD_FROM=ghcr.io/sbarkar/znacht:latest
FROM ${BUILD_FROM}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq curl && rm -rf /var/lib/apt/lists/*
COPY run.sh /run.sh
RUN chmod +x /run.sh
ENV ZNACHT_DATA_DIR=/config ZNACHT_HOUSEHOLD=/config/household.yaml ZNACHT_HOST=0.0.0.0
CMD ["/run.sh"]
