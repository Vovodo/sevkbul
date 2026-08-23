# ─── Stage 1: Build ───────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --prefer-offline

COPY . .

# VITE_API_URL → Coolify'da Build Args olarak gir
ARG VITE_API_URL=https://sevkbulapi.rfqcollector.com
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────
FROM nginx:alpine AS runner

# Özel nginx config (SPA routing + health endpoint)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Build çıktısı
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
