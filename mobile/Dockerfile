# ─── Stage 1: Build ───────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Bağımlılıkları önce kopyala (layer cache)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --prefer-offline

# Kaynak kodu kopyala
COPY . .

# Production build: Capacitor native olmadan web olarak build edilir.
# Android APK için Android Studio veya Gradle pipeline kullanılmalı.
# Bu image mobil web tarayıcısı için optimize edilmiş web önizleme sağlar.
ARG VITE_API_URL=https://sevkbulapi.rfqcollector.com
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────
FROM nginx:alpine AS runner

# SPA fallback + mobil cache optimizasyonu
RUN echo 'server { \
  listen 80; \
  root /usr/share/nginx/html; \
  index index.html; \
  gzip on; \
  gzip_types text/plain text/css application/javascript application/json; \
  location / { \
    try_files $uri $uri/ /index.html; \
  } \
  location ~* \.(js|css|png|jpg|svg|ico|woff2)$ { \
    expires 1y; \
    add_header Cache-Control "public, immutable"; \
  } \
  location /health { \
    return 200 "ok"; \
    add_header Content-Type text/plain; \
  } \
}' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
