# URLSnip

A production-grade URL shortener built on a microservices architecture, deployed on Kubernetes with full observability — metrics, logs, and alerting included.

Shorten a URL, track redirects in real time, and query analytics — all backed by AWS-native services (DynamoDB, SQS, S3), containerized with Docker, orchestrated with Kubernetes, and monitored with Prometheus, Grafana, and Loki.

---

## Architecture

```mermaid
graph TD
    Client([Client])

    subgraph K8s["Kubernetes Cluster (Floci EKS / k3s)"]
        SH[shortener-service\nFastAPI · port 8000]
        RD[redirect-service\nFastAPI · port 8001]
        AN[analytics-service\nFastAPI · port 8002]
        RE[(Redis\nCache)]

        SH -->|warm cache| RE
        RD -->|lookup| RE
    end

    subgraph AWS["AWS Services (Floci)"]
        DY[(DynamoDB\nurlsnip table)]
        SQ[SQS\nurlsnip-events]
        S3[(S3\nurlsnip-backups)]
    end

    subgraph OBS["Observability Stack"]
        PR[Prometheus]
        GR[Grafana]
        LK[Loki + Promtail]
    end

    Client -->|POST /shorten| SH
    Client -->|GET /:code| RD
    Client -->|GET /stats| AN

    SH -->|put_item| DY
    SH -->|send_message| SQ
    RD -->|get_item fallback| DY
    AN -->|receive_message| SQ
    AN -->|update clicks| DY
    SH -->|backup export| S3

    K8s -->|metrics /metrics| PR
    PR --> GR
    LK -->|scrape pod logs| K8s
    LK --> GR
```

---

## Services

### shortener-service
Accepts a long URL and returns a short code. Writes the mapping to DynamoDB, warms the Redis cache, and publishes a `created` event to SQS.

**Endpoints**
- `POST /shorten` — `{"url": "https://..."}` → `{"code": "xUsbVp", "short_url": "..."}`
- `GET /links` — list all shortened URLs
- `GET /health` — health check

### redirect-service
Resolves a short code to its original URL and issues a `302` redirect. Checks Redis first for sub-millisecond lookups, falls back to DynamoDB on cache miss.

**Endpoints**
- `GET /:code` — `302 Found` → original URL
- `GET /health` — health check

### analytics-service
Consumes SQS events asynchronously and tracks click counts per code in DynamoDB.

**Endpoints**
- `GET /stats/:code` — `{"code": "xUsbVp", "url": "...", "clicks": 4}`
- `GET /stats` — all codes with click counts
- `GET /health` — health check

---

## Data Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant SH as shortener-service
    participant RD as redirect-service
    participant AN as analytics-service
    participant DY as DynamoDB
    participant RE as Redis
    participant SQ as SQS

    C->>SH: POST /shorten {"url": "https://github.com"}
    SH->>DY: put_item {code, url, clicks: 0}
    SH->>RE: SET url:xUsbVp → https://github.com (TTL 1h)
    SH->>SQ: send_message {code, url, event: "created"}
    SH-->>C: {"code": "xUsbVp"}

    C->>RD: GET /xUsbVp
    RD->>RE: GET url:xUsbVp
    RE-->>RD: https://github.com (cache hit)
    RD-->>C: 302 → https://github.com

    SQ-->>AN: receive_message {code: "xUsbVp"}
    AN->>DY: update_item clicks += 1
    AN->>SQ: delete_message

    C->>AN: GET /stats/xUsbVp
    AN->>DY: get_item {code: "xUsbVp"}
    DY-->>AN: {url, clicks: 1}
    AN-->>C: {"code": "xUsbVp", "clicks": 1}
```

---

## Infrastructure

All AWS resources are provisioned via Terraform targeting Floci — a free, open-source local AWS emulator. The same Terraform HCL runs against real AWS with zero changes.

```mermaid
graph LR
    TF[Terraform]

    TF -->|aws_dynamodb_table| DY[(DynamoDB\nurlsnip)]
    TF -->|aws_sqs_queue| SQ[SQS\nurlsnip-events]
    TF -->|aws_s3_bucket| S3[(S3\nurlsnip-backups)]
    TF -->|aws_s3_bucket_versioning| S3
```

| Resource | Type | Purpose |
|---|---|---|
| `urlsnip` | DynamoDB table | Stores code → URL mappings + click counts |
| `urlsnip-events` | SQS standard queue | Async event bus between shortener and analytics |
| `urlsnip-backups` | S3 bucket (versioned) | Link export backups |

---

## Kubernetes

All services run in the `urlsnip` namespace with readiness/liveness probes, resource limits, and Horizontal Pod Autoscalers.

```mermaid
graph TD
    subgraph urlsnip["namespace: urlsnip"]
        SH_D[Deployment: shortener\nreplicas: 2–5]
        RD_D[Deployment: redirect\nreplicas: 2–10]
        AN_D[Deployment: analytics\nreplicas: 1–3]

        SH_S[Service: shortener-service\nClusterIP :8000]
        RD_S[Service: redirect-service\nClusterIP :8001]
        AN_S[Service: analytics-service\nClusterIP :8002]
        RE_S[Service: redis-service\nClusterIP :6379]

        SH_H[HPA: shortener-hpa\nCPU target 50%]
        RD_H[HPA: redirect-hpa\nCPU target 50%]
        AN_H[HPA: analytics-hpa\nCPU target 60%]

        SH_D --> SH_S
        RD_D --> RD_S
        AN_D --> AN_S
        SH_H -.->|scales| SH_D
        RD_H -.->|scales| RD_D
        AN_H -.->|scales| AN_D
    end
```

---

## Observability

```mermaid
graph LR
    subgraph Cluster["Kubernetes Cluster"]
        P[Pods\n/metrics]
        L[Pod Logs]
    end

    subgraph Monitoring["namespace: monitoring"]
        PR[Prometheus\nscrapes every 15s]
        PT[Promtail\nlog shipper]
        LK[Loki\nlog aggregation]
        GR[Grafana\ndashboards + alerts]
    end

    P -->|scrape| PR
    L -->|tail| PT
    PT --> LK
    PR --> GR
    LK --> GR
```

| Tool | Role |
|---|---|
| Prometheus | Scrapes `/metrics` from all pods every 15s |
| Grafana | Dashboards for request rate, latency, pod CPU/memory |
| Loki | Centralized log aggregation from all pods |
| Promtail | Ships pod logs to Loki |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Services | Python 3.11, FastAPI, Uvicorn |
| Cache | Redis 7 |
| Database | AWS DynamoDB (via Floci) |
| Queue | AWS SQS (via Floci) |
| Storage | AWS S3 (via Floci) |
| Containers | Docker, Docker Compose |
| Orchestration | Kubernetes (k3s via Floci EKS) |
| IaC | Terraform 1.15+ |
| Monitoring | Prometheus, Grafana, Loki, Promtail |
| Image Baking | Packer (ops toolbox) |
| Local AWS | Floci (free LocalStack alternative) |

---

## Project Structure

```
urlsnip/
├── services/
│   ├── shortener-service/
│   │   ├── app/main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── redirect-service/
│   │   ├── app/main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── analytics-service/
│       ├── app/main.py
│       ├── Dockerfile
│       └── requirements.txt
├── docker-compose.yml
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── dynamodb.tf
│   ├── sqs.tf
│   └── s3.tf
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── shortener/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── hpa.yaml
│   ├── redirect/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── hpa.yaml
│   └── analytics/
│       ├── deployment.yaml
│       ├── service.yaml
│       └── hpa.yaml
├── monitoring/
│   ├── prometheus/values.yaml
│   ├── grafana/values.yaml
│   └── loki/values.yaml
└── packer/
    └── ops-toolbox.pkr.hcl
```

---

## Running Locally

### Prerequisites

- Docker Desktop
- Terraform
- kubectl
- Helm
- Floci CLI
- AWS CLI

### Start

```bash
# Set AWS env (Floci uses dummy creds)
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export KUBECONFIG=~/.kube/urlsnip-local

# Start Floci (local AWS)
docker-compose up floci -d

# Provision AWS resources
cd terraform && terraform apply -auto-approve && cd ..

# Build and run services locally
docker-compose up --build

# Or deploy to Kubernetes
docker-compose up floci -d
# load images into k3s then:
kubectl apply -f k8s/
```

### Test

```bash
# Shorten a URL
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com"}'

# Redirect
curl -v http://localhost:8001/<code>

# Analytics
curl http://localhost:8002/stats/<code>
```

---

## Terraform Commands

```bash
cd terraform
terraform init       # initialise providers
terraform plan       # preview changes
terraform apply      # provision resources
terraform destroy    # tear everything down
terraform state list # inspect managed resources
terraform output     # print outputs
```

## Kubernetes Commands

```bash
kubectl get all -n urlsnip
kubectl get pods -n urlsnip -w
kubectl logs -n urlsnip -l app=shortener -f
kubectl describe pod -n urlsnip -l app=redirect
kubectl top pods -n urlsnip
kubectl get hpa -n urlsnip
kubectl scale deployment shortener -n urlsnip --replicas=4
kubectl rollout restart deployment/shortener -n urlsnip
kubectl rollout undo deployment/shortener -n urlsnip
kubectl rollout history deployment/shortener -n urlsnip
kubectl exec -it -n urlsnip <pod> -- /bin/sh
```