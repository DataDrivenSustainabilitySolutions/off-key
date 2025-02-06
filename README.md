# Project Setup

## Windows Setup
Setup Fundamentals:
1. Set up a virtual environment
2. Run  `python.exe -m pip install --upgrade pip`
3. Run `uv python install`
4. In `.\backend\` run `uv sync`. This will create the file `uv.lock`



4. [Install Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
5. [PyCharm Docker Integration](https://www.jetbrains.com/help/pycharm/docker-compose.html#scale-service)
6. [Install Yarn](https://github.com/yarnpkg/yarn/releases/download/v1.22.4/yarn-1.22.4.msi)
7. [Installation Guide (Windows)](https://geekflare.com/dev/how-to-install-yarn-on-windows/)

Setup Yarn:
1. Navigate to the frontend folder `cd .\frontend\`
2. Initialize `yarn` with `yarn init -y`
3. After the `package.json` was successfully saved install respective packages by `yarn install`
4. This procedure should create the file `yarn.lock` in `.\frontend\`
5. Run the `docker-compose.yml` or just run the frontend individually with `yarn start` in `.\frontend\`

**The `.env.example` have to be renamed to `.env` with actual values.**

Changes in the code may result in immediate changes when `yarn start` was used.
For docker compositions, navigate to `.\infrastructure\` and run `docker-compose up --build`.
Everytime this is done navigate **before** into `.\frontend\` and run `yarn install`.

## Query dockerized postgres
1. Run the respective postgres container (`docker-compose.yml`)
2. In the local terminal run `docker exec -it postgres_db psql -U admin -d offkey_pg`
3. The pg-terminal should open. Command should be ended by `;`

## Docker Commands
`docker stop <container-name>` for stopping a specific container.<br>
`docker rm <container-name>` for removing a specific container.<br>
`docker-compose up --build -d` for rebuilding the whole composition.<br>
`docker volume ls` shows the volume locations (e.g, persistence for the database).<br>
`docker volume rm <volume_name>` shows the volume locations (e.g, persistence for the database).<br>