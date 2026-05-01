# syntax=docker.io/docker/dockerfile:1
###################################################
# Builder stage which pulls in all dependencies   #
###################################################
FROM node:24-alpine as builder

ENV NPM_CONFIG_CACHE=/root/.npm

# This layer is cached until package-lock.json or package.json change, which are
# only temporarily mounted into the build container since we don't need
# them in the production one.
#
# ALWAYS run `npm ci` locally before debugging Docker builds.
# Issues with dependencies are often present locally as well.
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=bind,source=package-lock.json,target=package-lock.json \
    --mount=type=bind,source=package.json,target=package.json \
    npm ci

###################################################
# Create runner                                   #
###################################################
FROM node:24-alpine as runner

LABEL org.opencontainers.image.source="https://github.com/DataDrivenSustainabilitySolutions/off-key"

USER node

WORKDIR /src

# Optional: add node binaries to search path.
ENV PATH=/src/node_modules/.bin:$PATH

# Copy in all the dependencies without the npm cache
# SECURITY: Change the ownership to user node and group node in one step.
COPY --from=builder --chown=node:node ./node_modules/ ./node_modules/
# TODO: production build (--from=builder dist/)
# Copy project files
COPY . .

EXPOSE 5173

# See https://vite.dev/guide/cli
CMD ["vite"]
