# HA add-on wrapper around the same engine image. Build context is the repository root.
ARG BUILD_FROM=ghcr.io/sbarkar/znacht:latest
FROM ${BUILD_FROM}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq curl && rm -rf /var/lib/apt/lists/*
COPY addon/znacht/run.sh /run.sh
RUN chmod +x /run.sh
ENV ZNACHT_DATA_DIR=/config ZNACHT_HOUSEHOLD=/config/household.yaml ZNACHT_HOST=0.0.0.0
CMD ["/run.sh"]
