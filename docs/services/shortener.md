# shortener-service

The shortener is the entry point for creating short links. It's the only write-heavy service in the stack.

**Port:** 8000  
**Source:** `services/shortener-service/`  
**Image:** `ghcr.io/OWNER/urlsnip-shortener`

## Endpoints

### GET /health

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "service": "shortener"}
```

### POST /shorten

Creates a new short link.

```bash
curl -s -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.python.org/3/library/asyncio.html"}' | jq
```

```json
{
  "code": "aB3xYz",
  "short_url": "http://localhost:8001/aB3xYz"
}
```

Request schema:
```json
{"url": "string (required)"}
```

Errors:
- `422 Unprocessable Entity` — if `url` field is missing or not a string

### GET /links

Scans the entire DynamoDB table and returns all shortened links.

```bash
curl -s http://localhost:8000/links | jq
```

```json
{
  "links": [
    {"code": "aB3xYz", "url": "https://docs.python.org/...", "clicks": 3},
    {"code": "mN7pQr", "url": "https://github.com/...", "clicks": 0}
  ]
}
```

Note: this is a full table scan — fine for development but would need pagination in production.

### GET /metrics

Prometheus metrics endpoint. Returns text/plain in the Prometheus exposition format.

```bash
curl http://localhost:8000/metrics
```

Key metrics exposed:
- `http_requests_total{method, handler, status}` — counter
- `http_request_duration_seconds{method, handler, le}` — histogram

## Code generation

```python
def generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))
```

- Character set: `[a-zA-Z0-9]` = 62 characters
- Length: 6 characters
- Possible codes: 62^6 = 56,800,235,584 (~56 billion)
- Collision probability with 1 million links: ~0.0009% (negligible for this scale)

There is no collision check — if two requests happen to generate the same code at the same millisecond, the second `put_item` will silently overwrite the first. For production use, you'd add a conditional write or check-then-write.

## DynamoDB write

```python
table = dynamodb.Table(TABLE_NAME)
table.put_item(Item={"code": code, "url": req.url, "clicks": 0})
```

The item schema:
| Attribute | Type | Description |
|---|---|---|
| `code` | String (hash key) | 6-char short code |
| `url` | String | Original long URL |
| `clicks` | Number | Initialized to 0 |

## Redis cache warm

```python
cache.set(f"url:{code}", req.url, ex=3600)
```

The key is `url:{code}`. TTL is 3600 seconds (1 hour). This ensures the first redirect hits Redis rather than DynamoDB, even immediately after creation.

## SQS publish

```python
if QUEUE_URL:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=f'{{"code": "{code}", "url": "{req.url}", "event": "created"}}',
    )
```

The message body is a JSON string. If `SQS_QUEUE_URL` env var is empty (e.g. in Docker Compose without an SQS queue), this step is skipped silently.

## Environment variables

| Variable | Docker Compose value | Kubernetes ConfigMap value |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://floci:4566` | `http://172.21.0.2:4566` |
| `AWS_DEFAULT_REGION` | `us-east-1` | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | `test` | `test` |
| `AWS_SECRET_ACCESS_KEY` | `test` | `test` |
| `REDIS_HOST` | `redis` | `redis-service` |
| `REDIS_PORT` | `6379` | `6379` |
| `DYNAMODB_TABLE` | `urlsnip` | `urlsnip` |
| `SQS_QUEUE_URL` | `http://floci:4566/000000000000/urlsnip-events` | `http://172.21.0.2:4566/000000000000/urlsnip-events` |

## Kubernetes resources

- Deployment: 2 replicas minimum
- HPA: scales 2–5 replicas at 50% CPU
- Service: `shortener-service` ClusterIP on port 8000
- Resources per pod: 100m–250m CPU, 128Mi–256Mi memory

## Dockerfile notes

The Dockerfile in `services/shortener-service/` installs `requirements.txt` and starts with `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Images are built for `linux/arm64` to match the Mac M4 and k3s environment.
