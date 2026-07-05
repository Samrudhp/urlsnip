# Startup runbook

Complete sequence to bring the entire urlsnip stack up from a cold Mac. Follow in order.

---

## Phase 1 — Host prerequisites

```bash
# 1. Start Docker Desktop (if not already running)
# Launch from Applications or:
open -a Docker

# Wait for Docker to be ready
docker info > /dev/null 2>&1 && echo "Docker ready" || echo "waiting..."

# 2. Set shell environment variables (or confirm they're in ~/.zshrc)
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566
export KUBECONFIG=~/.kube/urlsnip-local
```

Expected: no errors, Docker daemon responds to `docker info`.

---

## Phase 2a — Local development (Docker Compose path)

Use this path when you want to iterate on code quickly without Kubernetes overhead.

```bash
cd /path/to/urlsnip

# Start everything: Floci + Redis + all 3 services
docker compose up --build

# Expected output (in order):
# floci         | Floci ready
# floci-init-1  | AWS resources created
# redis-1       | Ready to accept connections
# shortener-1   | INFO: Application startup complete.
# redirect-1    | INFO: Application startup complete.
# analytics-1   | INFO: Application startup complete.
```

Verify:
```bash
curl http://localhost:8000/health   # {"status":"ok","service":"shortener"}
curl http://localhost:8001/health   # {"status":"ok","service":"redirect"}
curl http://localhost:8002/health   # {"status":"ok","service":"analytics"}
```

---

## Phase 2b — Kubernetes path

Use this path for the full production-like setup.

### Step 1: Start Floci (standalone)

```bash
docker run -d \
  --name floci \
  -p 4566:4566 \
  -e FLOCI_HOSTNAME=floci \
  -e FLOCI_STORAGE_MODE=hybrid \
  -v /var/run/docker.sock:/var/run/docker.sock \
  floci/floci:latest

# Wait for Floci health
until curl -sf http://localhost:4566/_floci/health; do
  echo "Waiting for Floci..."; sleep 2
done
echo "Floci ready"
```

### Step 2: Provision AWS resources with Terraform

```bash
cd /path/to/urlsnip/terraform

terraform init
terraform apply -auto-approve

# Expected outputs:
# dynamodb_table_name = "urlsnip"
# sqs_queue_url = "http://localhost:4566/000000000000/urlsnip-events"
# s3_bucket_name = "urlsnip-backups"
```

Verify:
```bash
aws dynamodb list-tables --endpoint-url http://localhost:4566
# {"TableNames": ["urlsnip"]}
aws sqs list-queues --endpoint-url http://localhost:4566
# {"QueueUrls": ["http://localhost:4566/000000000000/urlsnip-events"]}
```

### Step 3: Start or resume the EKS cluster

```bash
# Check if the cluster container already exists (from a previous session)
docker ps -a | grep floci-eks-urlsnip-cluster
```

If the container exists but is stopped:
```bash
docker start floci-eks-urlsnip-cluster
sleep 10
```

If the container doesn't exist (first time or was deleted):
```bash
aws eks create-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1

# Wait for ACTIVE (~60 seconds)
until aws eks describe-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --query "cluster.status" \
  --output text | grep -q "ACTIVE"; do
  echo "Waiting for cluster..."; sleep 5
done
echo "Cluster ACTIVE"
```

### Step 4: Configure kubectl

```bash
aws eks update-kubeconfig \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1 \
  --kubeconfig ~/.kube/urlsnip-local

export KUBECONFIG=~/.kube/urlsnip-local

kubectl get nodes
# NAME                         STATUS   ROLES
# floci-eks-urlsnip-cluster    Ready    control-plane,master
```

### Step 5: Create image pull secret (first time or if deleted)

```bash
export GITHUB_USER=your-username
export GITHUB_TOKEN=ghp_your_token
bash scripts/create-ghcr-secret.sh
```

### Step 6: Apply Kubernetes manifests

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/shortener/
kubectl apply -f k8s/redirect/
kubectl apply -f k8s/analytics/
```

### Step 7: Load images into k3s (if not using CI/CD)

```bash
for SVC in shortener redirect analytics; do
  docker build --platform linux/arm64 \
    -t ghcr.io/OWNER/urlsnip-${SVC}:latest \
    services/${SVC}-service/
  docker save ghcr.io/OWNER/urlsnip-${SVC}:latest \
    -o /tmp/urlsnip-${SVC}.tar
  docker cp /tmp/urlsnip-${SVC}.tar \
    floci-eks-urlsnip-cluster:/tmp/urlsnip-${SVC}.tar
  docker exec floci-eks-urlsnip-cluster \
    ctr images import /tmp/urlsnip-${SVC}.tar
done
```

### Step 8: Verify pods are healthy

```bash
kubectl get pods -n urlsnip -w
# Wait until all pods show 1/1 Running

kubectl get hpa -n urlsnip
# All HPAs should show current replicas >= minReplicas
```

### Step 9: Port-forward and test

```bash
kubectl port-forward svc/shortener-service 8000:8000 -n urlsnip &
kubectl port-forward svc/redirect-service  8001:8001 -n urlsnip &
kubectl port-forward svc/analytics-service 8002:8002 -n urlsnip &
sleep 2

curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
```

---

## Phase 3 — Observability (optional)

```bash
# Install Prometheus + Grafana
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values monitoring/prometheus/values.yaml

# Install Loki
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm install loki grafana/loki \
  --namespace monitoring \
  --values monitoring/loki/values.yaml
helm install promtail grafana/promtail \
  --namespace monitoring \
  --values monitoring/loki/promtail-values.yaml

# Apply alert rules and Loki datasource
kubectl apply -f monitoring/prometheus/alerts.yaml
kubectl apply -f monitoring/grafana/loki-datasource.yaml

# Access Grafana
kubectl port-forward svc/prometheus-stack-grafana 3000:80 -n monitoring &
open http://localhost:3000
# Login: admin / admin123
```

---

## Phase 4 — GitHub Actions runner (for CI/CD)

```bash
# If the runner isn't already running
cd ~/actions-runner
./svc.sh status   # check

# Start it if stopped
./svc.sh start
```

Verify the runner shows as online in GitHub: **Settings → Actions → Runners**.

---

## Full health check summary

```bash
# Floci
curl -s http://localhost:4566/_floci/health | jq

# DynamoDB
aws dynamodb list-tables --endpoint-url http://localhost:4566

# Services (after port-forward)
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# Kubernetes
kubectl get pods -n urlsnip
kubectl get hpa  -n urlsnip
kubectl get pods -n monitoring

# Runner
cd ~/actions-runner && ./svc.sh status
```
