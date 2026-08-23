FROM python:3.12-slim

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları (önce kopyala - Docker layer cache için)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kaynak kodu
COPY . .

# Çalışma zamanı ortam değişkenleri (Coolify'da override edilebilir)
ENV DATABASE_URL="sqlite:///./sevkbul.db"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# SQLite için kalıcı veri dizini
RUN mkdir -p /app/data

EXPOSE 8000

# Sağlık kontrolü
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
