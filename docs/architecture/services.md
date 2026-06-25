# Services deep-dive

## shortener-service

**Port:** 8000  
**Image:** `ghcr.io/OWNER/urlsnip-shortener`  
**Source:** `services/shortener-service/`

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check — returns `{"status":"ok","service":"shortener"}` |
| POST | `/shorten` | Create a short link |
| GET | `/links` | List all links (DynamoDB scan) |
| GET | `/metrics` | Prometheus metrics (injected by prometheus-fastapi-instrumentator) |

### POST /shorten

Request body:
```json
{ "url": "https://www.example.com/some/very/long/path" }
```

Response:
```json
{
  "code": "aB3xYz",
  "short_url": "http://localhost:8001/aB3xYz"
}
```

The code is 6 random characters drawn from `[a-zA-Z0-9]` — 62^6 = ~56 billion possible codes.

### What happens on POST /shorten

1. Generate 6-char code via `random.choices(string.ascii_letters + string.digits, k=6)`
2. `dynamodb.Table("urlsnip").put_item(Item={"code": code, "url": url, "clicks": 0})`
3. `redis.set("url:{code}", url, ex=3600)` — 1-hour TTL
4. If `SQS_QUEUE_URL` is set: `sqs.send_message(QueueUrl=..., MessageBody='{"code":"..","url":"..","event":"created"}')`
5. Return the code and constructed short URL

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | Floci endpoint |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | `test` | Fake credential for Floci |
| `AWS_SECRET_ACCESS_KEY` | `test` | Fake credential for Floci |
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `DYNAMODB_TABLE` | `urlsnip` | DynamoDB table name |
| `SQS_QUEUE_URL` | `` (empty) | Full SQS queue URL — if empty, SQS publish is skipped |

In Kubernetes these come from the `urlsnip-config` ConfigMap. `AWS_ENDPOINT_URL` is set to `http://172.21.0.2:4566` (the Floci container IP on the Docker bridge network).

### Dependencies

- DynamoDB table `urlsnip` must exist
- Redis must be reachable
- SQS queue `urlsnip-events` must exist if `SQS_QUEUE_URL` is set

---

## redirect-service

**Port:** 8001  
**Image:** `ghcr.io/OWNER/urlsnip-redirect`  
**Source:** `services/redirect-service/`

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns `{"status":"ok","service":"redirect"}` |
| GET | `/{code}` | Resolve and redirect |
| GET | `/metrics` | Prometheus metrics |

### GET /{code}

On a cache hit (Redis has `url:{code}`): returns HTTP 302 to the cached URL immediately. No DynamoDB call made.

On a cache miss:
1. `dynamodb.Table("urlsnip").get_item(Key={"code": code})`
2. If not found: 404 `{"detail": "Short URL not found"}`
3. If found: warms the cache with a 1-hour TTL, returns HTTP 302

This service intentionally does not increment click counters itself. That's the analytics service's job via SQS.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | Floci endpoint |
| `AWS_DEFAULT_REGION` | `us-east-1` | |
| `AWS_ACCESS_KEY_ID` | `test` | |
| `AWS_SECRET_ACCESS_KEY` | `test` | |
| `REDIS_HOST` | `localhost` | |
| `REDIS_PORT` | `6379` | |
| `DYNAMODB_TABLE` | `urlsnip` | |

Note: redirect-service has no `SQS_QUEUE_URL` — it has no SQS dependency.

### Dependencies

- Redis (cache-first lookup)
- DynamoDB (fallback)

---

## analytics-service

**Port:** 8002  
**Image:** `ghcr.io/OWNER/urlsnip-analytics`  
**Source:** `services/analytics-service/`

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns `{"status":"ok","service":"analytics"}` |
| GET | `/stats/{code}` | Click stats for a single code |
| GET | `/stats` | Stats for all codes (DynamoDB scan) |
| GET | `/metrics` | Prometheus metrics |

### GET /stats/{code}

```json
{
  "code": "aB3xYz",
  "url": "https://www.example.com/...",
  "clicks": 14
}
```

### Background SQS polling

On startup (`@app.on_event("startup")`), a daemon thread is launched that calls `sqs.receive_message` in a tight loop with `WaitTimeSeconds=5` (long polling). For each message:

1. Parse the JSON body, extract `code`
2. `dynamodb.Table.update_item(Key={"code": code}, UpdateExpression="ADD clicks :inc", ExpressionAttributeValues={":inc": 1})`
3. Delete the message from the queue

If `SQS_QUEUE_URL` is empty the loop spins but does nothing. Any exception is caught, printed, and the loop continues — the service never crashes due to SQS errors.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | Floci endpoint |
| `AWS_DEFAULT_REGION` | `us-east-1` | |
| `AWS_ACCESS_KEY_ID` | `test` | |
| `AWS_SECRET_ACCESS_KEY` | `test` | |
| `DYNAMODB_TABLE` | `urlsnip` | |
| `SQS_QUEUE_URL` | `` (empty) | Full SQS queue URL |

### Dependencies

- DynamoDB
- SQS (optional — stats endpoints work even if queue is empty)

---

## Shared infrastructure

All three services use:

- `prometheus-fastapi-instrumentator==6.1.0` — auto-instruments all routes, exposes `/metrics` with `http_requests_total`, `http_request_duration_seconds` histograms
- `boto3==1.35.0` — AWS SDK, pointed at Floci
- `fastapi==0.115.0` + `uvicorn==0.30.6` — ASGI server, Dockerfiles start with `uvicorn app.main:app --host 0.0.0.0 --port <PORT>`
