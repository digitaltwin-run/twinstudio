FROM python:3.12-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir "paho-mqtt>=2.1,<3" "httpx>=0.28,<1"
COPY services/mqtt-gateway/gateway.py /app/gateway.py
CMD ["python", "/app/gateway.py"]
