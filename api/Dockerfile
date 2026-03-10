FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY api.py .

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
