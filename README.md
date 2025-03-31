# Predictive Maintenance Platform

## Setup

The use of `Python 3.12` is recommended.

### Infrastructure
1. [Install Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
2. Optinal: [PyCharm Docker Integration](https://www.jetbrains.com/help/pycharm/docker-compose.html#scale-service)
3. [Install Yarn](https://github.com/yarnpkg/yarn/releases/download/v1.22.4/yarn-1.22.4.msi) ([Installation Guide (Windows)](https://geekflare.com/dev/how-to-install-yarn-on-windows/))
4. Install Python dependencies in `backend` in a `venv`.

### Frontend Dependencies
1. Navigate into `frontend`
2. Dependencies from the `package.json`can be installed by `yarn install` (or `yarn`)

## Commands

### General Docker Commands
`docker ps -a` for listing all docker images.<br>
`docker logs <container-name> --follow` for seeing logs in real-time.<br>
`docker-compose down` for disconnecting all containers.<br>
`docker stop <container-name>` for stopping a specific container.<br>
`docker rm <container-name>` for removing a specific container.<br>
`docker-compose up --build` for rebuilding the whole composition (runs `docker-compose.yml`).<br>
`docker volume ls` shows the volume locations (e.g, persistence for the database).<br>
`docker volume ls -qf dangling=true` removes all volumes without respective container.<br>
`docker volume rm <volume_name>` shows the volume locations (e.g, persistence for the database).<br>

#### Complete Container Rebuild
1. Stop all docker container
2. Remove all docker container
3. Remove all volumes
4. Rebuild via docker-compose

### Dockerized PostgeSQL Inspection
1. Run the respective postgres container (`docker-compose.yml`)
2. In the local terminal run `docker exec -it postgres_database psql -U postgres -d postgres`
3. The pg-terminal should open. Command should be ended by `;` (!)

## Application Access

The different components of the application can be accessed after `docker-compose up --build`.
Keep in mind that `Docker Desktop` needs to be running for interacting with `Docker`.
- Access the `backend` (APIs) under `http://localhost:8000/`
  - Access the API documentation under `http://localhost:8000/docs`
- Access the `frontend` (UI) under `http://localhost:5173/`

## TODO
- MQTT Zugriff
  - MQTT Proxy
    - Schreibt Daten in Datenbank
- UI Service Konfiguration (IaaS)
  - Monitoring Service (ML+Sensoren)
    - Container dynamisch aufsetzen (DB Vorlage; "MonitoringService Table")
