# Loki

Loki provides centralized log aggregation for the urlsnip namespace. Promtail runs as a DaemonSet, tails pod logs, and pushes them to Loki. Grafana queries Loki for log visualization.

## Deployment

Loki and Promtail are deployed via separate Helm charts into the `monitoring` namespace.

```bash
# Add Grafana Helm repo (if not already added)
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Install Loki (single-binary mode, filesystem storage)
helm install loki grafana/loki \
  --namespace monitoring \
  --create-namespace \
  --values monitoring/loki/values.yaml

# Install Promtail
helm install promtail grafana/promtail \
  --namespace monitoring \
  --values monitoring/loki/promtail-values.yaml
```

## Loki configuration

`monitoring/loki/values.yaml` deploys Loki in single-binary mode (1 replica) with filesystem storage — appropriate for a local dev setup:

```yaml
loki:
  auth_enabled: false        # no multi-tenancy
  storage:
    type: filesystem         # no S3/GCS needed
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        schema: v13

singleBinary:
  replicas: 1
```

`auth_enabled: false` means queries don't need an `X-Scope-OrgID` header.

Loki listens on port 3100 inside the cluster at `http://loki.monitoring.svc.cluster.local:3100`.

## Promtail configuration

`monitoring/loki/promtail-values.yaml` configures Promtail to:

1. Discover pods in the `urlsnip` namespace via Kubernetes SD
2. Apply a pipeline that extracts `level` and `message` fields from JSON log lines
3. Re-label pods with `app`, `namespace`, `pod`, and `container` labels
4. Push to Loki at `http://loki:3100/loki/api/v1/push`

Key scrape config:
```yaml
- job_name: urlsnip-pods
  kubernetes_sd_configs:
    - role: pod
      namespaces:
        names:
          - urlsnip
  relabel_configs:
    - source_labels: [__meta_kubernetes_pod_label_app]
      target_label: app
    - source_labels: [__meta_kubernetes_namespace]
      target_label: namespace
    - source_labels: [__meta_kubernetes_pod_name]
      target_label: pod
```

## How logs flow from pods to Loki

```
Pod stdout/stderr
  → kubelet writes to /var/log/pods/...
  → Promtail DaemonSet tails those files
  → Promtail parses and labels each line
  → Promtail POSTs to Loki HTTP push API
  → Loki indexes labels, stores log chunks on filesystem
  → Grafana queries Loki via LogQL
```

All three urlsnip services write logs to stdout via Uvicorn. FastAPI's default log format includes the request method, path, status, and response time:

```
INFO:     172.17.0.1:54321 - "POST /shorten HTTP/1.1" 200 OK
INFO:     172.17.0.1:54322 - "GET /aB3xYz HTTP/1.1" 302 Found
```

## Querying logs in Grafana

Open Grafana → Explore → select **Loki** datasource.

### Basic queries

```logql
# All logs from urlsnip namespace
{namespace="urlsnip"}

# Logs from shortener service only
{namespace="urlsnip", app="shortener"}

# Logs from redirect service only
{namespace="urlsnip", app="redirect"}

# Logs from analytics service only
{namespace="urlsnip", app="analytics"}

# Logs from a specific pod
{namespace="urlsnip", pod="shortener-abc123-xyz"}
```

### Filtering by content

```logql
# All errors in urlsnip
{namespace="urlsnip"} |= "ERROR"

# 500 responses in redirect
{namespace="urlsnip", app="redirect"} |= "500"

# 404 responses (code not found)
{namespace="urlsnip", app="redirect"} |= "404"

# Logs mentioning a specific short code
{namespace="urlsnip"} |= "aB3xYz"

# SQS poll errors in analytics
{namespace="urlsnip", app="analytics"} |= "SQS poll error"

# Startup messages
{namespace="urlsnip"} |= "Application startup complete"
```

### Log rate queries

```logql
# Request rate from logs (lines per second, 1m window)
rate({namespace="urlsnip"}[1m])

# Error rate from logs
rate({namespace="urlsnip"} |= "ERROR" [1m])

# 404 rate on redirect service
rate({namespace="urlsnip", app="redirect"} |= "404" [1m])
```

### Parsing log fields

```logql
# Extract the HTTP status code and filter on 5xx
{namespace="urlsnip"}
  | regexp `"(?P<method>\w+) .+ HTTP/1\.\d" (?P<status>\d{3})`
  | status =~ "5.."
```

## Verifying Loki is working

```bash
# Check Loki pod is running
kubectl get pods -n monitoring | grep loki

# Check Promtail pods (one per node)
kubectl get pods -n monitoring | grep promtail

# Direct Loki query via API
kubectl port-forward svc/loki 3100:3100 -n monitoring &
curl "http://localhost:3100/loki/api/v1/labels"
# Should return {"status":"success","data":["app","namespace","pod","container",...]}

# Query recent logs
curl -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="urlsnip"}' \
  --data-urlencode "start=$(date -v-5M +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000" \
  | jq '.data.result[0].values[:3]'
```
