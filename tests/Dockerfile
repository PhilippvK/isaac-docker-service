FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends zstd chromium && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt api/requirements.txt
COPY tests/requirements.txt tests/requirements.txt
RUN pip install --no-cache-dir -r tests/requirements.txt
COPY api/ api/
COPY tests/ tests/
COPY worker/ worker/
COPY client/ client/
CMD ["python", "-m", "pytest", "-q", "tests"]
