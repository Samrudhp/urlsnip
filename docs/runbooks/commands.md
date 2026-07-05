# Commands cheatsheet

Every command used throughout the urlsnip project, grouped by tool.

---

## Docker

```bash
# Build a service image for arm64
docker build --platform linux/arm64 \
  -t ghcr.io/OWNER/urlsnip-shortener:latest \
  services/shortener-service/

# Build with a specific tag
docker build --platform linux/arm64 \
  -t ghcr.io/OWNER/urlsnip-shortener:$(git rev-parse HEAD) \
  services/shortener-service/

# Push to ghcr.io
docker push ghcr.io/OWNER/urlsnip-shortener:latest

# Pull from ghcr.io
docker pull ghcr.io/OWNER/urlsnip-shortener:latest

# Login to ghcr.io
echo $GITHUB_TOKEN | docker login ghcr.io -u OWNER --password-stdin

# Save image to tar
docker save ghcr.io/OWNER/urlsnip-shortener:latest -o /tmp/urlsnip-shortener.tar

# Load image from tar
docker load -i /tmp/urlsnip-shortener.tar

# Copy file into a container
docker cp /tmp/urlsnip-shortener.tar floci-eks-urlsnip-cluster:/tmp/urlsnip-shortener.tar

# Execute command in a running container
docker exec floci-eks-urlsnip-cluster ctr images import /tmp/urlsnip-shortener.tar
docker exec -it floci-eks-urlsnip-cluster bash

# List all images
docker images | grep urlsnip

# Remove a specific image
docker rmi ghcr.io/OWNER/urlsnip-shortener:latest

# Remove all stopped containers
docker container prune -f

# Remove unused images
docker image prune -f

# Full system prune
docker system prune -f

# Get container IP address
docker inspect floci \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'

# Start/stop a named container
docker start floci-eks-urlsnip-cluster
docker stop floci-eks-urlsnip-cluster

# List all containers (including stopped)
docker ps -a

# List running containers
docker ps

# View container logs
docker logs floci --tail 50 -f
```

---

## Docker Compose

```bash
# Start everything (build if needed)
docker compose up --build

# Start in background
docker compose up -d --build

# Stop (keep containers)
docker compose stop

# Stop and remove containers
docker compose down

# Stop, remove containers and volumes
docker compose down -v

# Rebuild a specific service
docker compose up --build shortener

# View logs (all services)
docker compose logs -f

# View logs (specific service)
docker compose logs -f shortener
docker compose logs -f redirect
docker compose logs -f analytics

# List running services
docker compose ps

# Exec into a service
docker compose exec shortener bash
docker compose exec redis redis-cli

# Run a one-off command
docker compose run --rm shortener python -c "from app.main import app; print('ok')"
```

---

## Terraform

```bash
# Change to terraform directory first
cd terraform/

# Initialize (download providers)
terraform init

# Initialize without backend (for CI)
terraform init -backend=false -input=false

# Preview changes
terraform plan

# Plan with explicit endpoint override
terraform plan -var="aws_endpoint=http://localhost:4566"

# Apply changes
terraform apply

# Apply without interactive prompt
terraform apply -auto-approve

# Destroy all resources
terraform destroy
terraform destroy -auto-approve

# Validate configuration syntax
terraform validate

# List managed resources
terraform state list

# Show a specific resource
terraform state show aws_dynamodb_table.urlsnip

# Import an existing resource
terraform import aws_dynamodb_table.urlsnip urlsnip

# Show outputs
terraform output
terraform output sqs_queue_url

# Refresh state from actual infrastructure
terraform refresh

# Format .tf files
terraform fmt
```

---

## kubectl

```bash
# Context / config
export KUBECONFIG=~/.kube/urlsnip-local
kubectl config view
kubectl config current-context
kubectl cluster-info

# Nodes
kubectl get nodes
kubectl describe node floci-eks-urlsnip-cluster

# Namespaces
kubectl get namespaces
kubectl apply -f k8s/namespace.yaml
kubectl delete namespace urlsnip

# Apply manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/shortener/
kubectl apply -f k8s/redirect/
kubectl apply -f k8s/analytics/
kubectl apply -f k8s/ --recursive

# Delete manifests
kubectl delete -f k8s/shortener/ --ignore-not-found
kubectl delete namespace urlsnip

# Pods
kubectl get pods -n urlsnip
kubectl get pods -n urlsnip -w              # watch
kubectl get pods -n urlsnip -o wide         # show node/IP
kubectl describe pod <pod-name> -n urlsnip
kubectl logs <pod-name> -n urlsnip
kubectl logs <pod-name> -n urlsnip -f       # follow
kubectl logs <pod-name> -n urlsnip --previous  # crashed container
kubectl logs deployment/shortener -n urlsnip
kubectl exec -it <pod-name> -n urlsnip -- bash

# Deployments
kubectl get deployments -n urlsnip
kubectl describe deployment shortener -n urlsnip
kubectl rollout status deployment/shortener -n urlsnip --timeout=120s
kubectl rollout history deployment/shortener -n urlsnip
kubectl rollout undo deployment/shortener -n urlsnip

# Update image
kubectl set image deployment/shortener \
  shortener=ghcr.io/OWNER/urlsnip-shortener:$(git rev-parse HEAD) \
  -n urlsnip

# Restart all pods in a deployment (rolling restart)
kubectl rollout restart deployment/shortener -n urlsnip
kubectl rollout restart deployment/redirect deployment/analytics -n urlsnip

# Services
kubectl get svc -n urlsnip
kubectl describe svc shortener-service -n urlsnip

# HPA
kubectl get hpa -n urlsnip
kubectl describe hpa shortener-hpa -n urlsnip

# ConfigMap
kubectl get configmap urlsnip-config -n urlsnip -o yaml
kubectl apply -f k8s/configmap.yaml
kubectl edit configmap urlsnip-config -n urlsnip

# Secrets
kubectl get secret ghcr-secret -n urlsnip
kubectl create secret docker-registry ghcr-secret \
  --namespace urlsnip \
  --docker-server=ghcr.io \
  --docker-username=OWNER \
  --docker-password=$GITHUB_TOKEN
kubectl delete secret ghcr-secret -n urlsnip

# Port-forward (always use service, not pod)
kubectl port-forward svc/shortener-service 8000:8000 -n urlsnip &
kubectl port-forward svc/redirect-service  8001:8001 -n urlsnip &
kubectl port-forward svc/analytics-service 8002:8002 -n urlsnip &
kubectl port-forward svc/prometheus-stack-grafana 3000:80 -n monitoring &
kubectl port-forward svc/prometheus-stack-kube-prom-prometheus 9090:9090 -n monitoring &
kubectl port-forward svc/loki 3100:3100 -n monitoring &

# Kill port-forwards
pkill -f "kubectl port-forward"

# All resources in namespace
kubectl get all -n urlsnip
kubectl get all -n monitoring

# Events (useful for debugging Pending/CrashLoop)
kubectl get events -n urlsnip --sort-by='.lastTimestamp'
```

---

## Helm

```bash
# Add repos
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo add grafana \
  https://grafana.github.io/helm-charts
helm repo update

# Install
helm install prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values monitoring/prometheus/values.yaml

helm install loki grafana/loki \
  --namespace monitoring \
  --values monitoring/loki/values.yaml

helm install promtail grafana/promtail \
  --namespace monitoring \
  --values monitoring/loki/promtail-values.yaml

# Upgrade (apply values changes)
helm upgrade prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values monitoring/prometheus/values.yaml

# List releases
helm list -n monitoring
helm list --all-namespaces

# Get values used by a release
helm get values prometheus-stack -n monitoring

# Uninstall
helm uninstall prometheus-stack -n monitoring
helm uninstall loki -n monitoring
helm uninstall promtail -n monitoring
```

---

## AWS CLI (against Floci)

```bash
# Prerequisite env vars
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566

# DynamoDB
aws dynamodb list-tables --endpoint-url http://localhost:4566
aws dynamodb describe-table --table-name urlsnip --endpoint-url http://localhost:4566
aws dynamodb scan --table-name urlsnip --endpoint-url http://localhost:4566
aws dynamodb get-item \
  --table-name urlsnip \
  --key '{"code": {"S": "aB3xYz"}}' \
  --endpoint-url http://localhost:4566
aws dynamodb put-item \
  --table-name urlsnip \
  --item '{"code": {"S": "test01"}, "url": {"S": "https://example.com"}, "clicks": {"N": "0"}}' \
  --endpoint-url http://localhost:4566

# SQS
aws sqs list-queues --endpoint-url http://localhost:4566
aws sqs get-queue-url \
  --queue-name urlsnip-events \
  --endpoint-url http://localhost:4566
aws sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/urlsnip-events \
  --attribute-names ApproximateNumberOfMessages \
  --endpoint-url http://localhost:4566
aws sqs receive-message \
  --queue-url http://localhost:4566/000000000000/urlsnip-events \
  --endpoint-url http://localhost:4566
aws sqs send-message \
  --queue-url http://localhost:4566/000000000000/urlsnip-events \
  --message-body '{"code":"test01","url":"https://example.com","event":"created"}' \
  --endpoint-url http://localhost:4566
aws sqs purge-queue \
  --queue-url http://localhost:4566/000000000000/urlsnip-events \
  --endpoint-url http://localhost:4566

# S3
aws s3 ls --endpoint-url http://localhost:4566
aws s3 ls s3://urlsnip-backups --endpoint-url http://localhost:4566
aws s3api head-bucket --bucket urlsnip-backups --endpoint-url http://localhost:4566
aws s3 cp somefile.json s3://urlsnip-backups/backup.json \
  --endpoint-url http://localhost:4566

# EKS
aws eks create-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1
aws eks describe-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --query "cluster.status"
aws eks update-kubeconfig \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1 \
  --kubeconfig ~/.kube/urlsnip-local
aws eks delete-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566
```

---

## Floci

```bash
# Health check
curl http://localhost:4566/_floci/health

# Start standalone
docker run -d \
  --name floci \
  -p 4566:4566 \
  -e FLOCI_HOSTNAME=floci \
  -e FLOCI_STORAGE_MODE=hybrid \
  -v /var/run/docker.sock:/var/run/docker.sock \
  floci/floci:latest

# Stop
docker stop floci

# Start again (preserves hybrid storage state)
docker start floci

# Get Floci container's Docker bridge IP (needed for k8s ConfigMap)
docker inspect floci \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'

# View Floci logs
docker logs floci --tail 50 -f
```

---

## Packer

```bash
# Initialize plugins
packer init packer/ops-toolbox.pkr.hcl

# Validate HCL
packer validate packer/ops-toolbox.pkr.hcl

# Build the ops toolbox image
packer build packer/ops-toolbox.pkr.hcl

# Build with a specific tag
packer build -var "image_tag=v1.0.0" packer/ops-toolbox.pkr.hcl

# Run the ops toolbox interactively
docker run -it \
  -e KUBECONFIG=/root/.kube/urlsnip-local \
  -v ~/.kube:/root/.kube \
  -v $(pwd):/workspace \
  urlsnip-ops-toolbox:latest
```

---

## GitHub Actions runner

```bash
# Check runner status
cd ~/actions-runner && ./svc.sh status

# Start runner
cd ~/actions-runner && ./svc.sh start

# Stop runner
cd ~/actions-runner && ./svc.sh stop

# View runner logs (macOS launchd)
tail -f ~/Library/Logs/actions.runner.*.log

# Re-register runner (if registration expired)
cd ~/actions-runner
./config.sh \
  --url https://github.com/OWNER/urlsnip \
  --token RUNNER_REGISTRATION_TOKEN \
  --name urlsnip-mac-runner \
  --labels self-hosted,macOS,arm64 \
  --replace
```

---

## Service curl commands

```bash
# Health checks
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# Shorten a URL
curl -s -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | jq

# Follow a redirect
curl -L http://localhost:8001/aB3xYz

# See redirect without following
curl -v http://localhost:8001/aB3xYz 2>&1 | grep -E "< HTTP|< Location"

# List all links
curl -s http://localhost:8000/links | jq

# Get stats for a code
curl -s http://localhost:8002/stats/aB3xYz | jq

# Get all stats
curl -s http://localhost:8002/stats | jq

# Prometheus metrics
curl http://localhost:8000/metrics | grep http_requests

# Loki health (after port-forward)
curl http://localhost:3100/ready
curl http://localhost:3100/loki/api/v1/labels
```
