FROM nvidia/cuda:13.2.0-base-ubuntu24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin exporter

WORKDIR /app
COPY exporter.py /app/exporter.py
USER 10001:10001
EXPOSE 9400
CMD ["python3", "/app/exporter.py"]

