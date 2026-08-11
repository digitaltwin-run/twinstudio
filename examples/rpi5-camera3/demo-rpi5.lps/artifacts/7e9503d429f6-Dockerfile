FROM python:3.12-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir "Pillow>=11,<12"
COPY vision_app.py /app/vision_app.py
ENTRYPOINT ["python", "/app/vision_app.py"]
