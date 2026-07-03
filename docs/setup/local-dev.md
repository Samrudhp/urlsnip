# Local development

Docker Compose is the fastest way to run the full stack locally. It starts Floci, waits for it to be healthy, creates the DynamoDB table and SQS queue, starts Redis, then starts all three services.

## Start everything

```bash
cd /path/to/urlsnip

docker compose up --build
```

The `--build` flag rebuilds all three service images from source. On subsequent runs when only code has changed, Docker's layer cache makes rebuilds fast.

Expected startup sequence in logs:
1. `floci` container starts and passes health check
2. `floci-init` runs AWS CLI commands to create the `urlsnip` DynamoDB table and `urlsnip-events` SQS queue, then exits with `AWS resources created`
3. `redis` passes health check
4. `shortener`, `redirect`, `analytics` start

Full healthy state looks like this:

```
floci-init-1  | {
floci-init-1  |     "TableDescription": { ... }
floci-init-1  | }
floci-init-1  | {
floci-init-1  |     "QueueUrl": "http://floci:4566/000000000000/urlsnip-events"
floci-init-1  | }
floci-init-1  | AWS resources created
shortener-1   | INFO:     Application startup complete.
redirect-1    | INFO:     Application startup complete.
analytics-1   | INFO:     Application startup complete.
```

## Testing the services with curl

```bash
# Health checks
curl http://localhost:8000/health
# {"status":"ok","service":"shortener"}

curl http://localhost:8001/health
# {"status":"ok","service":"redirect"}

curl http://localhost:8002/health
# {"status":"ok","service":"analytics"}

# Shorten a URL
curl -s -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/torvalds/linux"}' | jq
# {
#   "code": "aB3xYz",
#   "short_url": "http://localhost:8001/aB3xYz"
# }

# Follow the redirect (curl -L follows it automatically)
curl -L http://localhost:8001/aB3xYz
# You'll land on the GitHub page

# Or see the redirect without following it
curl -v http://localhost:8001/aB3xYz 2>&1 | grep -E "< HTTP|< Location"
# < HTTP/1.1 302 Found
# < Location: https://github.com/torvalds/linux

# Check analytics
curl http://localhost:8002/stats/aB3xYz | jq
# {
#   "code": "aB3xYz",
#   "url": "https://github.com/torvalds/linux",
#   "clicks": 1
# }

# List all shortened links
curl http://localhost:8000/links | jq
```

## Browsing the auto-generated API docs

FastAPI generates interactive Swagger UI for each service:

- Shortener: http://localhost:8000/docs
- Redirect: http://localhost:8001/docs
- Analytics: http://localhost:8002/docs

## Rebuilding after a code change

If you change a service's Python code, rebuild just that service:

```bash
docker compose up --build shortener
```

Or rebuild all and restart:

```bash
docker compose up --build
```

Docker Compose only rebuilds images whose context has changed.

## Useful Docker Compose commands

```bash
# Start in background (detached)
docker compose up -d --build

# View logs from a specific service
docker compose logs -f shortener
docker compose logs -f redirect
docker compose logs -f analytics

# View logs from all services
docker compose logs -f

# Stop everything (keeps volumes/containers)
docker compose stop

# Stop and remove containers
docker compose down

# Stop, remove containers, and remove volumes
docker compose down -v

# List running containers
docker compose ps

# Exec into a container
docker compose exec shortener bash
docker compose exec redis redis-cli

# Check DynamoDB table via AWS CLI (Floci)
aws dynamodb scan --table-name urlsnip \
  --endpoint-url http://localhost:4566

# Check SQS queue
aws sqs list-queues \
  --endpoint-url http://localhost:4566
```

## Common issue: floci-init SQS token error

If you see something like:
```
An error occurred (InvalidClientTokenId) when calling the CreateQueue operation
```

This usually means `floci-init` ran before Floci was fully ready. The health check in `docker-compose.yml` should prevent this but occasionally a timing issue occurs. Fix:

```bash
docker compose down
docker compose up --build
```

If it persists, check that no stale Floci container is holding port 4566:

```bash
docker ps | grep 4566
```
