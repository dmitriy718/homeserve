FROM python:3.12-slim
WORKDIR /app
COPY --chmod=0644 requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chmod=0644 app.py .
COPY --chmod=0644 test_app.py .
RUN useradd -r -u 10001 agent && mkdir -p /srv/agent-workspaces /srv/agent-artifacts /srv/agent-cache && chown -R agent:agent /srv/agent-workspaces /srv/agent-artifacts /srv/agent-cache
USER agent
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
