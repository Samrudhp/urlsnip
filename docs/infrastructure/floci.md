# Floci

## What Floci is

Floci is a free local AWS emulator that runs as a Docker container and exposes a single endpoint at `http://localhost:4566`. It emulates AWS services so you can develop and test against real AWS SDKs without a real AWS account or incurring any costs.

Floci is positioned as an alternative to LocalStack. Key differences from LocalStack:

- Floci is free with no feature gating behind a paid tier
- Floci's EKS emulation runs actual k3s inside Docker, giving you a real Kubernetes cluster rather than a mock API
- Floci uses `FLOCI_STORAGE_MODE=hybrid` which keeps service state persistent across container restarts by default

The Docker Compose image tag is `floci/floci:latest`. The compat image (`floci/floci:latest-compat`) includes the AWS CLI and is used for the `floci-init` init container.

## How Floci works

Floci runs as a single Docker container. It listens on port 4566 and multiplexes all AWS service APIs on that one port. The service is determined by the `Host` header or the URL path prefix.

When Docker Compose starts:
```yaml
floci:
  image: floci/floci:latest
  ports:
    - "4566:4566"
  environment:
    - FLOCI_HOSTNAME=floci
    - FLOCI_STORAGE_MODE=hybrid
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
```

The Docker socket mount is required for Floci's EKS emulation — it needs to spin up the k3s Docker container on the host.

## Services Floci emulates for urlsnip

| AWS Service | urlsnip usage |
|---|---|
| DynamoDB | `urlsnip` table — stores short codes, URLs, click counts |
| SQS | `urlsnip-events` queue — async events from shortener to analytics |
| S3 | `urlsnip-backups` bucket — versioned backup storage |
| EKS | `urlsnip-cluster` — real k3s Kubernetes cluster |

## Starting and stopping Floci

### With Docker Compose (recommended for development)

```bash
# Start (along with all services)
docker compose up

# Stop
docker compose down

# Stop and clean state
docker compose down -v
```

### Standalone (for Kubernetes-only work)

```bash
# Start
docker run -d \
  --name floci \
  -p 4566:4566 \
  -e FLOCI_HOSTNAME=floci \
  -e FLOCI_STORAGE_MODE=hybrid \
  -v /var/run/docker.sock:/var/run/docker.sock \
  floci/floci:latest

# Stop
docker stop floci

# Start again (state is preserved with hybrid mode)
docker start floci
```

## Verifying Floci is healthy

```bash
curl http://localhost:4566/_floci/health
# {"status":"ok"}
```

## Verifying AWS services were created

```bash
# Check DynamoDB table
aws dynamodb describe-table \
  --table-name urlsnip \
  --endpoint-url http://localhost:4566
# Should return table description with BillingModeSummary.BillingMode = PAY_PER_REQUEST

# List all tables
aws dynamodb list-tables \
  --endpoint-url http://localhost:4566
# {"TableNames": ["urlsnip"]}

# Check SQS queue
aws sqs get-queue-url \
  --queue-name urlsnip-events \
  --endpoint-url http://localhost:4566
# {"QueueUrl": "http://localhost:4566/000000000000/urlsnip-events"}

# List all queues
aws sqs list-queues \
  --endpoint-url http://localhost:4566

# Check S3 bucket
aws s3api head-bucket \
  --bucket urlsnip-backups \
  --endpoint-url http://localhost:4566

# List all buckets
aws s3 ls --endpoint-url http://localhost:4566
```

## Floci from inside Kubernetes pods

Pods cannot reach `localhost:4566` because `localhost` inside a pod refers to the pod itself. Instead, pods use the Docker bridge network IP.

The Floci container's IP on the default Docker bridge is typically `172.21.0.2`. This is hardcoded in the Kubernetes ConfigMap:

```yaml
data:
  AWS_ENDPOINT_URL: "http://172.21.0.2:4566"
  SQS_QUEUE_URL: "http://172.21.0.2:4566/000000000000/urlsnip-events"
```

To verify the current Floci IP:

```bash
docker inspect floci \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
# 172.21.0.2
```

If the IP changes (e.g. after recreating the container), update `k8s/configmap.yaml` and reapply:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/shortener deployment/redirect deployment/analytics -n urlsnip
```

## Accessing Floci data directly

```bash
# Scan the entire DynamoDB table
aws dynamodb scan \
  --table-name urlsnip \
  --endpoint-url http://localhost:4566

# Get a specific item
aws dynamodb get-item \
  --table-name urlsnip \
  --key '{"code": {"S": "aB3xYz"}}' \
  --endpoint-url http://localhost:4566

# Peek at SQS messages without consuming them
aws sqs receive-message \
  --queue-url http://localhost:4566/000000000000/urlsnip-events \
  --endpoint-url http://localhost:4566

# List S3 bucket contents
aws s3 ls s3://urlsnip-backups \
  --endpoint-url http://localhost:4566
```
