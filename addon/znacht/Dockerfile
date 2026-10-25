# HA add-on wrapper around the same engine image. The Supervisor builds it with this folder as context.
# The tag is this release's engine image, never `latest`: a rebuild of the add-on gets the code it was
# released with. scripts/check_versions.py keeps it equal to config.yaml's version.
FROM ghcr.io/sbarkar/znacht:0.2.0-rc.1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq curl && rm -rf /var/lib/apt/lists/*
COPY run.sh import_bundle.py /
RUN chmod +x /run.sh
ENV ZNACHT_DATA_DIR=/config ZNACHT_HOUSEHOLD=/config/household.yaml ZNACHT_HOST=0.0.0.0
CMD ["/run.sh"]
