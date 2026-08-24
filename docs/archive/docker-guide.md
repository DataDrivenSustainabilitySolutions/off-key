> [!WARNING]
> This page is **legacy / archived** and may be outdated.
> It is preserved for historical context only and is **not** the source of truth for current operations.
>
> Use current documentation instead:
- [Getting-Started](../getting-started.md)
- [Deployment-Modes](../operations/deployment-modes.md)
- [Testing-&-Debugging](../development/testing-debugging.md)
>
> You can also start from [Archive / Legacy Index](index.md).

---
- [Docker Command Cheatsheet](#docker-command-cheatsheet)
- [Deploying with Docker Compose](#deploying-with-docker-compose)
- [Deploying with Docker Swarm](#deploying-with-docker-swarm)
  * [DEV](#dev)
    + [Tips](#tips)
  * [QA](#qa)
    + [Preparing the stack](#preparing-the-stack)
    + [Deploying on master node](#deploying-on-master-node)
  * [PROD](#prod)
- [Docker Operations](#docker-operations)
    + [Building (Standalone) Docker Images](#building-standalone-docker-images)
    + [Inspecting Containers](#inspecting-containers)

# Docker Command Cheatsheet

`docker ps -a` for listing all docker images.<br>
`docker logs <container-name> --follow` for seeing logs in real-time.<br>
`docker compose down` for disconnecting all containers.<br>
`docker stop <container-name>` for stopping a specific container.<br>
`docker rm <container-name>` for removing a specific container.<br>
`docker compose up --build` for rebuilding the whole composition (runs `docker-compose.yml`).<br>
`docker volume ls` shows the volume locations (e.g, persistence for the database).<br>
`docker volume ls -qf dangling=true` removes all volumes without respective container.<br>
`docker volume rm <volume_name>` shows the volume locations (e.g, persistence for the database).<br>

# Deploying with Docker Compose

+ The `docker-proxy` service runs in PRIVILEGED mode.
  Easiest way to achieve this is by **ALWAYS** executing docker commands with `sudo`.
  > Alternatively you could set the necessary permissions to let a specific user mount the Docker socket.

 + **ALWAYS** execute docker compose commands from project root

 + To deploy the stack:
   ```bash
   docker compose up --build   # On first run OR to force rebuild
   docker compose up -d   # Detached mode
   ```
  + The backend uses Docker Swarm endpoints to manage the lifecycle of containers (in this context: services).
    You **MUST** have an active swarm for this to work.
    You **ONLY** need to initialize the swarm as detailed in [the first step of DEV](#dev).

  + To shut down the stack:
    ```bash
    # Either press Ctrl+C if running in attached (not -d) mode
    # OR
    docker compose down
    # OR
    docker compose down -v  # Removes all resources associated (volumes, networks, ...). Good for clean restart
    ```

> FRONTEND: maybe use https://github.com/garronej/vite-envs for env variables on runtime?

# Deploying with Docker Swarm

## DEV

- Initialize a docker swarm:

  ```bash
  default:~$ sudo docker swarm init --advertise-addr 127.0.0.1
  Swarm initialized: current node (kcy6t3n9f1jovs3vr0v3n6mac) is now a manager.

  To add a worker to this swarm, run the following command:

    docker swarm join --token SWMTKN-1-5pvjirdfcl0u56uu4eet4oe9nd12p2524dc4xk3mnrat70t0hh-c1m6lmze2fu0ffapapsvoexqg 127.0.0.1:2377
  ```
- Remove ALL resources created by Docker Compose:
  ```
  sudo docker compose down -v
  ```
- (Re)build API and Frontend:
  ```
  sudo docker compose build
  ```
- Duplicate the `docker-compose.swarm.yml` file:
  ```
  cp docker-compose.swarm.yml docker-compose.local-swarm.yml
  ```
  > This new file gets automatically ignored by git so you don't end up pushing unwanted changes
- Within this new copy, replace ALL instances of `node.role == worker` with `node.role == manager`.
  ```
  sed -i 's/node.role == worker/node.role == manager/g' docker-compose.local-swarm.yml
  ```
  > You can also run the dedicated replacement script from the root as `./dev/replace_node_role.sh docker-compose.local-swarm.yml`.
- If you're working on an IPv6-first machine, chances are that requests to `localhost` in your browser will never go through.

  To find it out, run `ping` in the console (`sudo apt install iputils-ping` if not installed).
  For an IPv6-first machine the output will look like this:
  ```
  default:~$ ping localhost
  PING localhost (::1) 56 data bytes
  64 bytes from localhost (::1): icmp_seq=1 ttl=64 time=0.027 ms
  64 bytes from localhost (::1): icmp_seq=2 ttl=64 time=0.033 ms
  ^C
  --- localhost ping statistics ---
  2 packets transmitted, 2 received, 0% packet loss, time 1039ms
  rtt min/avg/max/mdev = 0.027/0.030/0.033/0.003 ms
  ```
  If you see `::1` in the output, you'll need to force a redirection from [::1] to 127.0.0.1 first. The easiest way to accomplish this is with `socat`.
  ```
  sudo apt install socat                                                   # If not installed. Debian-based distros
  socat TCP6-LISTEN:8000,fork,reuseaddr,ipv6only=1 TCP4:127.0.0.1:8000 &   # Default 8000 API port. Update according to .env
  socat TCP6-LISTEN:5173,fork,reuseaddr,ipv6only=1 TCP4:127.0.0.1:5173 &   # Default 5173 Frontend port. Update according to .env
  ```
  > Alternatively, update your `/etc/hosts` in your OS. This is out-of-scope and at your own risk.

  You **MUST** run this before initializing the docker stack. Otherwise the connection will stall.

- Deploy the stack with:
  ```
  sudo docker compose -f docker-compose.local-swarm.yml config | (sed "/published:/s/\"//g") | (sed "/^name:/d") | sudo docker stack deploy -c - --detach=false "off-key-stack"
  ```

### Tips

- You can update the stack in-place by re-executing the command above with your saved changes.

  If you need a clean start, you can remove the stack with:
  ```
  sudo docker stack rm off-key-stack
  ```
- Any service launched through the backend will be started on worker nodes only. You can force its execution by removing this constraint.

  ```
  default:~$ sudo docker service ls
  ID             NAME                                                      MODE         REPLICAS   IMAGE     PORTS
  tqfmmbxn9kfa   monitoring-service-9b37dcef-a7cc-487c-9e07-811dd104c3e9   replicated   0/1        alpine

  default:~$ sudo docker service update --constraint-rm "node.role == worker" monitoring-service-9b37dcef-a7cc-487c-9e07-811dd104c3e9

  # Service will attempt to initialize
  ```

------

## QA

The following steps apply to a multi-node Swarm setup.

It's HIGHLY recommended that all nodes communicate with each other using a WireGuard/Tailscale network on top. For more details see [our security write-up](https://github.com/OliverHennhoefer/off-key/wiki/Swarm-PoC:-From-Containers-to-Services#the-swarm-vs-the-internet)

### Preparing the stack

On your developer machine

1. Log into GH registry:
 See https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic

2. Create a `compose.env` file with the following values:

```
API_IMAGE=ghcr.io/<your-gh-username>/off-key-api:qa
FRONTEND_IMAGE=ghcr.io/<your-gh-username>/off-key-frontend:qa
```

> NOTE: We should use the project's repo instead of per-user.

3. Build and push the docker images

```
sudo docker compose --env-file compose.env --env-file .env build
sudo docker compose --env-file compose.env --env-file .env push
```

### Deploying on master node

1. Log into GH registry:
 See https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic

2. Create/copy `compose.env` with the same values from the previous section.

3. Initialize the swarm with `docker swarm init`

> Using WireGuard: `docker swarm init --advertise-addr YOUR_WIREGUARD_IP`

4. Create encrypted networks

> NOTE: Remove any pre-existing networks that have the same name as the ones present in your docker-compose swarm file. The easiest way to achieve this is by removing any pre-existing compose (`sudo docker compose down -v`) or swarm (`sudo docker stack rm off-key-stack`) resources.

- For each network, execute:

```
docker network create \
  --opt encrypted \
  --driver overlay \
  --attachable \
  name-of-network-in-docker-swarm-yml
```

- Add the `external: true` property to each network specified in your swarm yml file.

5. Deploy the stack

```
sudo docker compose --env-file compose.env --env-file .env -f docker-compose.swarm.yml config | (sed "/published:/s/\"//g") | (sed "/^name:/d") | sudo docker stack deploy -c - --with-registry-auth "off-key-stack"
```

6. Let `SWARM WORKER(S)` join the docker swarm:

`docker swarm join --token <SWARM_TOKEN> <HOST_A_IP>:2377`

----

## PROD

WIP

---

# Docker Operations

### Building (Standalone) Docker Images
```bash
sudo docker compose build <service-name>
```

### Inspecting Containers
1. Run the respective standalone container or service (`docker-compose.yml`)
2. In the local terminal run `docker exec -it <container-name> <command to be passed on>`.

   ```bash
   docker exec -it timescaledb psql -U postgres -d postgres
   ```
