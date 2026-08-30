FROM python:3.12-slim
WORKDIR /app
COPY --chmod=0644 requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chmod=0644 app.py .
COPY --chmod=0644 test_app.py .
RUN useradd -r -u 10002 scheduler
# Compose overrides the runtime UID (user: "1000:1000"); this default USER only
# applies when the image is run outside compose and does not conflict with it.
USER scheduler
EXPOSE 8077
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8077"]
