# FROM python:3.11
FROM philippvk/isaac-quickstart-demo

WORKDIR /app

RUN apt-get update && apt-get install -y zstd tar

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY worker.py .
COPY run_retarget.sh /scripts/run_retarget.sh

RUN chmod +x /scripts/run_retarget.sh

CMD ["python", "worker.py"]
