FROM python:3.11

WORKDIR /app

COPY api/requirements.txt .
RUN pip install -r requirements.txt

COPY api/api.py api/dashboard.html ./
COPY worker/job_state.py .

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
