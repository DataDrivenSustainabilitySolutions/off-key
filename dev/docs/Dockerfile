# syntax=docker/dockerfile:1
FROM python:3.15-slim AS build
WORKDIR /docs
COPY requirements-docs.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-docs.txt
COPY zensical.toml ./
COPY docs ./docs
COPY dev/docs/llms.py ./dev/docs/llms.py
RUN zensical build --clean --strict && python dev/docs/llms.py site

FROM nginx:1.31.9-alpine-slim@sha256:5bfced78d24d644270bedb0a9968697042e38d5c03fb6354603df025279c1cbe
COPY --from=build /docs/site /usr/share/nginx/html
# Keep the server configuration with the build recipe.
COPY <<'NGINX' /etc/nginx/conf.d/default.conf
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    server_tokens off;
    # Cloudflare supplies HTTPS; directory redirects must retain that scheme.
    absolute_redirect off;
    add_header X-Content-Type-Options nosniff always;
    add_header Cache-Control "no-cache" always;
    location ~ \.md$ {
        types { }
        default_type text/markdown;
        charset utf-8;
        try_files $uri =404;
    }
    location / {
        try_files $uri $uri/ =404;
    }
    error_page 404 /404.html;
}
NGINX
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1
