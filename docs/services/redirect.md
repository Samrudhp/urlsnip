# redirect-service

The redirect service is the hot-path service. It handles every click on a short link and must respond as fast as possible.

**Port:** 8001  
**Source:** `services/redirect-service/`  
**Image:** `ghcr.io/OWNER/urlsnip-redirect`

## Endpoints

### GET /health

```bash
curl http://localhost:8001/health
```

```json
{"status": "ok", "service": "redirect"}
```

### GET /{code}

Resolves a short code and redirects to the original URL.

```bash
# Follow the redirect
curl -L http://localhost:8001/aB3xYz

# See the redirect without following
curl -v http://localhost:8001/aB3xYz 2>&1 | grep -E "< HTTP|< Location"
# < HTTP/1.1 302 Found
# < Location: https://docs.python.org/...
```

Response on success: `302 Found` with `Location` header.

Response on miss: `404 Not Found`
```json
{"detail": "Short URL not found"}
```

### GET /metrics

```bash
curl http://localhost:8001/metrics
```

## Cache-first lookup logic

The redirect service always checks Redis before touching DynamoDB. The full logic in `app/main.py`:

```python
@app.get("/{code}")
def redirect(code: str):
    # 1. Try Redis
    cached = cache.get(f"url:{code}")
    if cached:
        return RedirectResponse(url=cached, status_code=302)

    # 2. Fall back to DynamoDB
    table = dynamodb.Table(TABLE_NAME)
    result = table.get_item(Key={"code": code})
    item = result.get("Item")

    if not item:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # 3. Warm the cache for next time
    cache.set(f"url:{code}", item["url"], ex=3600)

    return RedirectResponse(url=item["url"], status_code=302)
```

**Cache hit** (~0.1ms): Redis returns the URL immediately. No DynamoDB call is made.

**Cache miss** (~2-5ms): DynamoDB is queried. If the code exists, the URL is written back to Redis with a 1-hour TTL before returning the redirect. The next request for the same code hits the cache.

**Not found**: Both Redis and DynamoDB return nothing — 404 is returned.

## 302 vs 301

The service returns `302 Found` (temporary redirect), not `301 Moved Permanently`. This is intentional: with 301, browsers cache the redirect indefinitely. If you ever needed to change where a short code points, browsers that cached the 301 would never pick up the change. 302 redirects are not cached by browsers, so every request goes through the service and gets the current URL.

## What this service does NOT do

- It does not increment click counters. That's async via SQS + analytics-service.
- It does not write to DynamoDB (only reads).
- It does not publish to SQS.
- It does not know about the shortener service at all.

This separation means the redirect service has no SQS dependency in its `requirements.txt` and no SQS client in its code.

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

Note: no `SQS_QUEUE_URL` — this service has no SQS dependency.

## Kubernetes resources

- Deployment: 2 replicas minimum — redirect gets the most traffic so it gets the most headroom
- HPA: scales 2–10 replicas at 50% CPU — highest max of all three services
- Service: `redirect-service` ClusterIP on port 8001
- Resources per pod: 100m–250m CPU, 128Mi–256Mi memory

The redirect HPA has a `maxReplicas` of 10, much higher than the shortener (5) and analytics (3). This reflects the expected traffic pattern: redirects are the high-volume operation.

## Liveness and readiness

Both probes hit `/health`:
- Readiness: initialDelaySeconds=5, periodSeconds=5
- Liveness: initialDelaySeconds=10, periodSeconds=10

If the service can't connect to Redis at startup, FastAPI still starts but the first redirect attempt will fail. The readiness probe won't catch this — for production you'd add a startup check that verifies Redis connectivity.
