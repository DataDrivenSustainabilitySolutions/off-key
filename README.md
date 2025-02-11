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
2. In the local terminal run `docker exec -it postgres_db psql -U postgres -d offkey_pg`
3. The pg-terminal should open. Command should be ended by `;`

For the timescale database execute `docker exec -it timescale_db psql -U admin -d offkey_pg`.

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
