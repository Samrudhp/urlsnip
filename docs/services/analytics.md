# analytics-service

The analytics service tracks click counts by consuming events from SQS asynchronously. It never blocks the redirect path.

**Port:** 8002  
**Source:** `services/analytics-service/`  
**Image:** `ghcr.io/OWNER/urlsnip-analytics`

## Endpoints

### GET /health

```bash
curl http://localhost:8002/health
```

```json
{"status": "ok", "service": "analytics"}
```

### GET /stats/{code}

Returns click statistics for a specific short code.

```bash
curl -s http://localhost:8002/stats/aB3xYz | jq
```

```json
{
  "code": "aB3xYz",
  "url": "https://docs.python.org/3/library/asyncio.html",
  "clicks": 14
}
```

Returns `404` if the code doesn't exist in DynamoDB.

### GET /stats

Returns statistics for all short codes (full DynamoDB scan).

```bash
curl -s http://localhost:8002/stats | jq
```

```json
{
  "stats": [
    {"code": "aB3xYz", "url": "https://...", "clicks": 14},
    {"code": "mN7pQr", "url": "https://...", "clicks": 2}
  ]
}
```

### GET /metrics

```bash
curl http://localhost:8002/metrics
```

## Background SQS polling thread

The analytics service starts a background thread at application startup. This thread polls SQS indefinitely.

```python
@app.on_event("startup")
def startup():
    t = threading.Thread(target=poll_sqs, daemon=True)
    t.start()
```

The thread is a `daemon=True` thread — it dies automatically when the main process exits (e.g. during a pod restart). A new thread is started on the next startup.

### The polling loop

```python
def poll_sqs():
    while True:
        if not QUEUE_URL:
            continue
        try:
            resp = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5,
            )
            for msg in resp.get("Messages", []):
                body = json.loads(msg["Body"])
                code = body.get("code")
                if code:
                    table = dynamodb.Table(TABLE_NAME)
                    table.update_item(
                        Key={"code": code},
                        UpdateExpression="ADD clicks :inc",
                        ExpressionAttributeValues={":inc": 1},
                    )
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
        except Exception as e:
            print(f"SQS poll error: {e}")
```

Key details:
- `MaxNumberOfMessages=10` — processes up to 10 messages per poll
- `WaitTimeSeconds=5` — long polling, blocks for 5 seconds waiting for messages before returning empty. This is more efficient than short polling (which returns immediately even if the queue is empty)
- `UpdateExpression="ADD clicks :inc"` — DynamoDB's atomic ADD operation increments the counter without needing a read-modify-write cycle
- `delete_message` is called after each message is processed — if the service crashes mid-batch, undeleted messages become visible again after 30 seconds (the `visibility_timeout_seconds` set in Terraform)
- Any exception is caught and printed. The loop continues regardless — the service never crashes due to a single malformed message or transient SQS error

### Message format

The message published by shortener-service:
```json
{"code": "aB3xYz", "url": "https://...", "event": "created"}
```

The analytics service only uses `code` from this message.

## Click counting with DynamoDB ADD

```python
table.update_item(
    Key={"code": code},
    UpdateExpression="ADD clicks :inc",
    ExpressionAttributeValues={":inc": 1},
)
```

`ADD` on a Number attribute is atomic in DynamoDB — concurrent increments from multiple analytics pods won't lose counts. No optimistic locking or transactions needed.

## Environment variables

| Variable | Docker Compose value | Kubernetes ConfigMap value |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://floci:4566` | `http://172.21.0.2:4566` |
| `AWS_DEFAULT_REGION` | `us-east-1` | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | `test` | `test` |
| `AWS_SECRET_ACCESS_KEY` | `test` | `test` |
| `DYNAMODB_TABLE` | `urlsnip` | `urlsnip` |
| `SQS_QUEUE_URL` | `http://floci:4566/000000000000/urlsnip-events` | `http://172.21.0.2:4566/000000000000/urlsnip-events` |

Note: no Redis dependency — analytics does not cache anything.

## Kubernetes resources

- Deployment: 1 replica minimum — analytics is background workload
- HPA: scales 1–3 replicas at 60% CPU
- Service: `analytics-service` ClusterIP on port 8002
- Resources per pod: 100m–250m CPU, 128Mi–256Mi memory

The analytics service gets fewer replicas than the others because it's not on the request path. Even at 1 replica, SQS buffers messages so no data is lost during restarts or scaling events.

## What to check if click counts aren't updating

1. Verify the SQS queue has messages:
   ```bash
   aws sqs get-queue-attributes \
     --queue-url http://localhost:4566/000000000000/urlsnip-events \
     --attribute-names ApproximateNumberOfMessages \
     --endpoint-url http://localhost:4566
   ```

2. Check analytics pod logs for SQS poll errors:
   ```bash
   kubectl logs -n urlsnip deployment/analytics -f
   ```

3. Verify `SQS_QUEUE_URL` is set correctly in the ConfigMap and the pod can reach `172.21.0.2:4566`.
