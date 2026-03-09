FROM node:20-alpine AS build

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY VERSION /app/VERSION
COPY web ./
RUN npm run build

FROM caddy:2.8-alpine

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/web/dist /srv

EXPOSE 80 443
