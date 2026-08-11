FROM python:3.12-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir "paho-mqtt>=2.1,<3" "Pillow>=11,<12"
COPY services/device-sim/simulator.py /app/simulator.py
CMD ["python", "/app/simulator.py"]
