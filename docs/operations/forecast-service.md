# Forecast service

The forecast service (`off-key-forecast`) holds pretrained forecasting models for
forecaster steps: Mistral's Timestral checkpoints, and a seasonal-naive baseline
that needs no weights. A RADAR worker or a Dojo worker sends the recent values of
one reading and gets quantile forecasts back, so no model and no weights live in a
worker. [Monitoring pipelines](../development/monitoring-pipelines.md) describes
the step itself.

## How it is deployed

Production runs one `forecast` task on a backend node, from its own image. The
image carries CPU-only PyTorch and the `timestral` package (the service's
`timestral` extra, locked in `backend/uv.lock`); its build fails when they are not
installed or cannot compute. No other image carries them.

- The service has no published port and no route. It joins the app network only,
  where workers reach it as `http://forecast:8020`.
- Every call but `/health/live` needs a bearer token. The service, the Dojo
  workers and every RADAR worker read it from the Swarm secret
  `FORECAST_API_TOKEN`; it is never in a container's environment. TACTIC copies
  the secret reference to each RADAR worker it starts, from the same template
  service as the worker's MQTT credentials.
- TACTIC hands the address (`TACTIC_FORECAST_API_URL`) to every RADAR worker and
  every preflight job as `FORECAST_API_URL`. A preflight job only checks that a
  service is named; it has no network and no token. The address is not part of a
  monitor's configuration fingerprint.
- A release waits for the task's health check and then asks `/health/live` from
  the app network (the readiness check `forecast endpoint`). It never waits for
  weights.

The token is derived from `internal_api_secret` unless the environment vault sets
`forecast_api_token` (at least 32 characters). The derivation is a one-way hash,
so a worker that holds the token learns nothing about the internal credential.

## Weights

Weights are not in the image. The first monitor or Dojo run that uses a checkpoint
asks the service for it, and the service downloads it from the Hugging Face Hub
into the `forecast_models` volume (`/models`). The backend node therefore needs
outbound HTTPS to `huggingface.co` and the hosts it redirects downloads to. Values
that arrive before the checkpoint is ready are counted as lost coverage, not
scored; the smallest checkpoint is ready within seconds.

The volume is node-local and outlives redeployments, so a checkpoint downloads
once. A task rescheduled to another backend node downloads what it is asked for
again.

Each checkpoint is pinned to the Hub commit it was tested at
(`forecast_timestral_checkpoints` in the `stack_prepare` role defaults, rendered
into `FORECAST_TIMESTRAL_MODELS` as `repo@commit`). `/v1/models` and every
forecast report that commit as the model's revision. To move a checkpoint to a
newer commit, change its pin and release; the new weights download on first use
and the old ones stay in the volume until it is cleaned.

The service offers all four checkpoints, because the composer offers them and a
step that names a checkpoint the service does not have ends its run. A checkpoint
that nobody uses is never downloaded or loaded.

## Sizing

Measured on a 4-core x86-64 machine with `FORECAST_TORCH_THREADS=2`, one series,
512 values of context, one step ahead (what a monitor asks with every value):

| Checkpoint | Download on a fast link | On disk | Forecast, median / 95th percentile |
| --- | --- | --- | --- |
| `mistralai/Timestral-5M` | 3 s | 21 MB | 17 ms / 30 ms |
| `mistralai/Timestral-28M` | 7 s | 111 MB | 59 ms / 67 ms |
| `mistralai/Timestral-123M` | 11 s | 490 MB | 134 ms / 164 ms |
| `mistralai/Timestral-209M` | 13 s | 837 MB | 212 ms / 231 ms |

Resident memory is about 85 MB before any model is loaded and grows as
checkpoints are used: 0.3 GB with the smallest loaded, 0.4 GB with the two
smallest, 0.9 GB with three and 1.7 GB with all four. Loading the largest
checkpoint peaks at 2.5 GB for a moment. A loaded checkpoint stays loaded until
the task restarts. A full batch of long series (16 series of 4,096 values, 96
steps ahead) did not raise that peak.

The defaults follow from this: a 4 GB memory limit and 2 CPUs
(`forecast_memory_limit`, `forecast_cpu_limit`), with 512 MB and a quarter CPU
reserved (`forecast_memory_reservation`, `forecast_cpu_reservation`). All
forecasts share those CPUs: a monitor that gets one value per second and uses the
largest checkpoint keeps the service busy about a fifth of the time, so many
monitors on the larger checkpoints need more CPUs or the smaller checkpoints.

## Settings

| Ansible variable | Default | Becomes |
| --- | --- | --- |
| `forecast_api_url` | `http://forecast:8020` | `TACTIC_FORECAST_API_URL` for TACTIC, `FORECAST_API_URL` for workers |
| `forecast_api_token` (vault, optional) | derived from `internal_api_secret` | Swarm secret `FORECAST_API_TOKEN` |
| `forecast_timestral_checkpoints` | the four checkpoints, each with its commit | `FORECAST_TIMESTRAL_MODELS` |
| `forecast_torch_threads` | `2` | `FORECAST_TORCH_THREADS` |
| `forecast_memory_limit`, `forecast_cpu_limit` | `4G`, `2` | the task's limits |
| `forecast_memory_reservation`, `forecast_cpu_reservation` | `512M`, `0.25` | the task's reservations |

[Environment variables](../reference/environment-variables.md#forecast-service)
lists what the service and the workers read.

## When something is wrong

| What you see | What it means |
| --- | --- |
| Preflight rejects a Timestral step with `forecast_service` | The worker's environment names no service: `TACTIC_FORECAST_API_URL` is empty. |
| A monitor's coverage drops while it keeps running | The service did not answer, or the checkpoint is still downloading. Scores resume by themselves; the model's series has no gap. |
| A run ends right after it starts | The step names a checkpoint that `FORECAST_TIMESTRAL_MODELS` does not offer. |
| `/v1/models` shows a checkpoint as `failed` | Its download failed; `error` says why (usually no route to the Hub). The next use asks again. |
| The release fails on `forecast endpoint` | The task is not running or not reachable on the app network; read its task errors and logs. |

To look at the service, ask it from a Dojo worker, which holds the token. On the
node that runs one:

```bash
docker exec "$(docker ps -q -f name=off-key_dojo-worker | head -1)" /app/bin/python -c \
  "from off_key_mqtt_radar.forecasting import service_client; [print(m.id, m.status, m.revision) for m in service_client().models()]"
```

## Local development

The local stacks leave the service out, because its image is large. Start it with
the `forecast` Compose profile and give the workers its address:

```bash
make local-up LOCAL_ARGS=--forecast
```

With plain Compose, set `FORECAST_API_URL=http://forecast:8020` in `.env` and run
`docker compose --profile forecast up -d --build`. A development machine uses no
token.

## Licence

The Timestral code is Apache 2.0. The weights are under Mistral AI's Modified MIT
licence; they are downloaded from Mistral's repositories at run time and are not
redistributed with this project.
