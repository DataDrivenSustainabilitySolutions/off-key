# syntax=docker.io/docker/dockerfile:1
###################################################
# Builder stage which pulls in all dependencies   #
###################################################
FROM node:24-alpine as builder

ENV YARN_CACHE_FOLDER=/root/.yarn

# TODO: yarn (v2-v4) install --immutable --production
# This layer is cached until yarn.lock or package.json change, which are
# only temporarily mounted into the build container since we don't need
# them in the production one.
#
# ALWAYS run `yarn install` locally before debugging Docker builds.
# Issues with dependencies are often present locally as well.
RUN --mount=type=cache,target=/root/.yarn \
    --mount=type=bind,source=yarn.lock,target=yarn.lock \
    --mount=type=bind,source=package.json,target=package.json \
    yarn install \
        --frozen-lockfile

###################################################
# Create runner                                   #
###################################################
FROM node:24-alpine as runner

USER node

WORKDIR /src

# Optional: add node binaries to search path.
ENV PATH=/src/node_modules/.bin:$PATH

# Copy in all the dependencies without yarn cache
# SECURITY: Change the ownership to user node and group node in one step.
COPY --from=builder --chown=node:node ./node_modules/ ./node_modules/
# TODO: production build (--from=builder dist/)
# Copy project files
COPY . .

EXPOSE 5173

# See https://vite.dev/guide/cli
CMD ["vite"]
