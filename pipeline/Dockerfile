
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY checkout.py /pipeline/checkout.py
COPY detect_project.py /pipeline/detect_project.py
COPY worker_api.py /pipeline/worker_api.py
COPY test_project.py /pipeline/test_project.py
COPY build_project.py /pipeline/build_project.py

CMD ["python", "/pipeline/checkout.py"]
