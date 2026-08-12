FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 curl \
    && rm -rf /var/lib/apt/lists/*
COPY components/housing-studio /app/components/housing-studio
COPY services/cad-worker/worker.py /app/worker.py
COPY services/cad-worker/scoped_brep_adapter.py /app/scoped_brep_adapter.py
RUN python -m pip install --upgrade pip && \
    python -m pip install -e "/app/components/housing-studio[llm]" "paho-mqtt>=2.1,<3"
RUN useradd --create-home --uid 10002 cad && mkdir -p /data && chown -R cad:cad /app /data
USER cad
CMD ["python", "/app/worker.py"]
