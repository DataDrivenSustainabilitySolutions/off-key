# syntax=docker.io/docker/dockerfile:1
FROM node:26-alpine AS dependencies

WORKDIR /src
ENV NPM_CONFIG_CACHE=/home/node/.npm

RUN chown node:node /src
COPY --chown=node:node package.json package-lock.json ./
USER node
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 npm ci

FROM dependencies AS development

LABEL org.opencontainers.image.source="https://github.com/DataDrivenSustainabilitySolutions/off-key" \
      org.opencontainers.image.description="Development server for the Off-Key frontend" \
      org.opencontainers.image.licenses="MIT"

COPY --chown=node:node . .

EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM dependencies AS build

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

COPY --chown=node:node . .
RUN npm run build

FROM nginx:1.30.4-alpine AS production

LABEL org.opencontainers.image.source="https://github.com/DataDrivenSustainabilitySolutions/off-key" \
      org.opencontainers.image.description="Production image for the Off-Key frontend" \
      org.opencontainers.image.licenses="MIT"

ENV API_UPSTREAM=api-gateway:8000 \
    NGINX_ENVSUBST_FILTER=API_UPSTREAM

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html

EXPOSE 5173
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1:5173/ || exit 1
