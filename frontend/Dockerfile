# syntax=docker.io/docker/dockerfile:1
###################################################
# Builder stage which pulls in all dependencies   #
###################################################
FROM node:23-alpine3.20 as builder

ENV YARN_CACHE_FOLDER=/root/.yarn

# TODO: yarn install --immutable --production
RUN --mount=type=cache,target=/root/.yarn \
    --mount=type=bind,source=yarn.lock,target=yarn.lock \
    --mount=type=bind,source=package.json,target=package.json \
    yarn install

###################################################
# Create runner                                   #
###################################################
FROM node:23-alpine3.20 as runner

WORKDIR /src

# Copy in all the dependencies we need, by avoiding
# installing them in this stage, we prevent Yarn
# from including additional cache files, which
# yields a slimmer image.

COPY                ./package.json  ./
COPY --from=builder ./node_modules/ ./node_modules/

EXPOSE 5173

CMD ["yarn", "dev"]