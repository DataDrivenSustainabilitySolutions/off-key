# Project Setup

## Windows Setup
Setup Fundamentals:
1. Set up a virtual environment
2. Run  `python.exe -m pip install --upgrade pip`
3. Run `uv python install`
4. In `.\backend\` run `uv sync`. This will create the file `uv.lock`


Setup Infrastructure:
1. [Install Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
2. [PyCharm Docker Integration](https://www.jetbrains.com/help/pycharm/docker-compose.html#scale-service)
3. [Install Yarn](https://github.com/yarnpkg/yarn/releases/download/v1.22.4/yarn-1.22.4.msi)
4. [Installation Guide (Windows)](https://geekflare.com/dev/how-to-install-yarn-on-windows/)

Setup Vue Project with Yarn (see [Vite Guide](https://vite.dev/guide/)):
1. Run `yarn create vite frontend --template vue`
2. Follow the instructions after the creation (`cd frontend`, then `yarn` then `yarn dev`)
3.

# New yarn dependencies
1. Go to frontend
2. rm node_modules (J) and rm yarn.lock
3. E.g. yarn add rollup@latest + yarn add @rollup/rollup-linux-x64-musl and/or yarn install should update package.json
4. npm i
5. npm rebuild
6. run docker-compose


what i need:
1. yarn add @types/react-router-dom
2. https://ui.shadcn.com/docs/installation/vite
3. npx shadcn@latest add input label card to add single components
3. yarn add recharts
4. yarn add axios

https://github.com/leoMirandaa/shadcn-landing-page

# Mailpit
For Mail verification (local) one needs a SMTP server. Mailpit in a Docker container runs
a lightweight webserver on the local machine. The UI is accessible under 'http://localhost:8025/'

# Error: Cannot find module @rollup/rollup-linux-x64-musl. npm has a bug related to optional dependencies (https://github.com/npm/cli/issues/4828).
#Please try `npm i` again after removing both package-lock.json and node_modules directory. 

**The `.env.example` have to be renamed to `.env` with actual values.**

Changes in the code may result in immediate changes when `yarn start` was used.
For docker compositions, navigate to `.\infrastructure\` and run `docker-compose up --build`.
Everytime this is done navigate **before** into `.\frontend\` and run `yarn install`.

## Query dockerized postgres
1. Run the respective postgres container (`docker-compose.yml`)
2. In the local terminal run `docker exec -it postgres_database psql -U postgres -d postgres`
3. The pg-terminal should open. Command should be ended by `;`

## Docker Commands
`docker ps -a` for listing all docker images.<br>
`docker logs <container-name> --follow` for seeing logs in real-time.<br>
`docker-compose down` for disconnecting all containers.<br>
`docker stop <container-name>` for stopping a specific container.<br>
`docker rm <container-name>` for removing a specific container.<br>
`docker-compose up --build -d` for rebuilding the whole composition (runs `docker-compose.yml`).<br>
`docker volume ls` shows the volume locations (e.g, persistence for the database).<br>
`docker volume ls -qf dangling=true` removes all volumes without respective container.<br>
`docker volume rm <volume_name>` shows the volume locations (e.g, persistence for the database).<br>

Restart everything:
1. Stop all docker container
2. Remove all docker container
3. Remove all volumes
4. Rebuild via docker-compose

Access under `http://localhost:8000/`

'https://sc-production.schoneberg.pionix.net
