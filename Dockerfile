FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 7860

ENV DATABASE_URL="sqlite:///./sevkbul.db"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
