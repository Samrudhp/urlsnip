# Architecture overview

## What the system does

urlsnip turns long URLs into short codes. Three independent FastAPI services cover the three distinct concerns: creating short links, resolving them, and counting clicks. Each service has a single job and communicates with the others only through shared storage or async messaging — never with direct HTTP calls between services.

## Services

| Service | Port | Responsibility |
|---|---|---|
| shortener-service | 8000 | Accepts a long URL, generates a 6-character alphanumeric code, writes to DynamoDB, warms the Redis cache, publishes a `created` event to SQS |
| redirect-service | 8001 | Accepts a short code, checks Redis first, falls back to DynamoDB, returns a 302 redirect |
| analytics-service | 8002 | Polls SQS in a background thread, increments click counters in DynamoDB, exposes stats endpoints |

## Communication model

- **Shortener → redirect** — no direct call. Both read the same DynamoDB table and Redis keyspace.
- **Shortener → analytics** — async via SQS. The shortener publishes a JSON message to the `urlsnip-events` queue. The analytics service polls that queue in a background daemon thread.
- **All services → DynamoDB** — synchronous boto3 calls to Floci at `http://172.21.0.2:4566` (inside k8s) or `http://localhost:4566` (in Docker Compose).
- **Shortener + redirect → Redis** — synchronous reads/writes. Redis is `redis-service.urlsnip.svc.cluster.local:6379` in Kubernetes, `redis:6379` in Docker Compose.

## Full system diagram

```mermaid
graph TD
    Client -->|POST /shorten| SVC_SHORT[shortener-service :8000]
    Client -->|GET /:code| SVC_REDIR[redirect-service :8001]
    Client -->|GET /stats/:code| SVC_ANA[analytics-service :8002]

    SVC_SHORT -->|put_item| DDB[(DynamoDB\nurlsnip table)]
    SVC_SHORT -->|SET url:code| REDIS[(Redis :6379)]
    SVC_SHORT -->|send_message| SQS[SQS\nurlsnip-events]

    SVC_REDIR -->|GET url:code| REDIS
    SVC_REDIR -->|get_item fallback| DDB

    SQS -->|poll receive_message| SVC_ANA
    SVC_ANA -->|update_item clicks++| DDB
    SVC_ANA -->|get_item| DDB

    subgraph Kubernetes urlsnip namespace
        SVC_SHORT
        SVC_REDIR
        SVC_ANA
        REDIS
    end

    subgraph Floci :4566
        DDB
        SQS
        S3[(S3\nurlsnip-backups)]
    end

    subgraph Observability monitoring namespace
        PROM[Prometheus] -->|scrape /metrics| SVC_SHORT
        PROM -->|scrape /metrics| SVC_REDIR
        PROM -->|scrape /metrics| SVC_ANA
        GRAFANA[Grafana] -->|query| PROM
        LOKI[Loki] -->|push| PROMTAIL[Promtail]
        PROMTAIL -->|tail pod logs| SVC_SHORT
        PROMTAIL -->|tail pod logs| SVC_REDIR
        PROMTAIL -->|tail pod logs| SVC_ANA
    end
```

## Why three services?

The redirect path is the hot path — it will receive an order of magnitude more traffic than the shortener. Separating it means you can scale the redirect deployment to 10 replicas without scaling the shortener at all. The analytics service is intentionally isolated on the slow path: if SQS processing lags, redirects still work perfectly.

## Storage boundaries

Each service only touches the DynamoDB table and Redis. There is no service-to-service HTTP call in the codebase. This means:

- Any service can be restarted without affecting the others mid-request
- The redirect service has no runtime dependency on the shortener service being healthy
- The analytics service can be taken down for maintenance without losing data (messages queue up in SQS)
