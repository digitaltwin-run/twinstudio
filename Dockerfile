FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates libgl1 libglu1-mesa libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY components/housing-studio ./components/housing-studio
RUN python -m pip install --upgrade pip && \
    python -m pip install "./components/housing-studio" ".[llm]"
COPY examples ./examples
COPY proto ./proto
COPY schemas ./schemas
COPY scripts ./scripts
COPY error ./error
RUN useradd --create-home --uid 10001 twinstudio && mkdir -p /data \
    && chown -R twinstudio:twinstudio /app /data
ARG TWINSTUDIO_BUILD_SHA=unknown
LABEL org.opencontainers.image.revision=$TWINSTUDIO_BUILD_SHA
USER twinstudio
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1
CMD ["uvicorn", "twinstudio.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
