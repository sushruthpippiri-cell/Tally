# The production front door (P16.12): one image that serves the built SPA and proxies the API.
# Built from the repository root: `docker build -f deploy/caddy/Dockerfile .`
FROM node:24.13.0-bookworm-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY fixtures/money-formatting.json /fixtures/money-formatting.json
RUN npm run build

FROM caddy:2-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
