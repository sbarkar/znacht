# Znacht engine. Multi-stage: build wheels with uv, run on a slim image as a non-root user.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /src
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
RUN uv sync --all-packages --no-dev --no-editable --frozen

FROM python:3.12-slim-bookworm
RUN useradd --system --create-home --uid 10001 znacht \
 && mkdir -p /data && chown znacht:znacht /data
COPY --from=build --chown=znacht:znacht /src/.venv /app/.venv
COPY --chown=znacht:znacht examples/household.example.yaml /app/household.example.yaml
ENV PATH="/app/.venv/bin:$PATH" \
    ZNACHT_DATA_DIR=/data \
    ZNACHT_HOUSEHOLD=/data/household.yaml \
    ZNACHT_PORT=8787 \
    HOME=/home/znacht
USER znacht
VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).status == 200 else 1)"
CMD ["znacht-engine"]
