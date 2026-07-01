# Prometheus

## Deployment

Prometheus is deployed via the `kube-prometheus-stack` Helm chart into the `monitoring` namespace.

```bash
# Add the Helm repo
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update

# Install with custom values
helm install prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values monitoring/prometheus/values.yaml
```

The `values.yaml` configures:
- `scrapeInterval: 15s` — Prometheus scrapes all targets every 15 seconds
- `evaluationInterval: 15s` — alert rules are evaluated every 15 seconds
- Additional scrape configs for the three urlsnip services
- Grafana enabled with `adminPassword: admin123`
- Node Exporter and kube-state-metrics enabled

## What Prometheus scrapes

### urlsnip services (custom scrape config)

Defined in `monitoring/prometheus/values.yaml`:

```yaml
additionalScrapeConfigs:
  - job_name: urlsnip-shortener
    static_configs:
      - targets: ['shortener-service.urlsnip.svc.cluster.local:8000']
    metrics_path: /metrics

  - job_name: urlsnip-redirect
    static_configs:
      - targets: ['redirect-service.urlsnip.svc.cluster.local:8001']
    metrics_path: /metrics

  - job_name: urlsnip-analytics
    static_configs:
      - targets: ['analytics-service.urlsnip.svc.cluster.local:8002']
    metrics_path: /metrics
```

### Cluster metrics

- **node-exporter** — CPU, memory, disk, network on each node
- **kube-state-metrics** — pod status, deployment replicas, HPA state, resource limits

## How FastAPI exposes /metrics

All three services use `prometheus-fastapi-instrumentator`:

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

This automatically:
- Creates `http_requests_total` counter with labels `{method, handler, status}`
- Creates `http_request_duration_seconds` histogram with labels `{method, handler}`
- Exposes both at the `/metrics` path using the standard Prometheus text format

Test it:
```bash
curl http://localhost:8000/metrics | grep http_requests
# http_requests_total{handler="/shorten",method="POST",status="2xx"} 42.0
# http_request_duration_seconds_bucket{handler="/shorten",method="POST",le="0.005"} 38.0
```

## Accessing the Prometheus UI

```bash
kubectl port-forward svc/prometheus-stack-kube-prom-prometheus \
  9090:9090 -n monitoring &

# Open in browser
open http://localhost:9090
```

## Useful PromQL queries

```promql
# Request rate per service (last 1 minute)
rate(http_requests_total[1m])

# Request rate for shortener only
rate(http_requests_total{job="urlsnip-shortener"}[1m])

# p99 latency per handler
histogram_quantile(0.99,
  rate(http_request_duration_seconds_bucket[5m])
)

# Error rate (5xx responses)
rate(http_requests_total{status=~"5.."}[5m])

# Error rate as a percentage of total
rate(http_requests_total{status=~"5.."}[5m])
  /
rate(http_requests_total[5m])

# Pod CPU usage in urlsnip namespace
rate(container_cpu_usage_seconds_total{namespace="urlsnip"}[5m])

# Pod memory usage
container_memory_working_set_bytes{namespace="urlsnip"}

# HPA current vs max replicas
kube_horizontalpodautoscaler_status_current_replicas{namespace="urlsnip"}
kube_horizontalpodautoscaler_spec_max_replicas{namespace="urlsnip"}

# Pods not ready
kube_pod_status_ready{namespace="urlsnip", condition="true"} == 0
```

## Applying alert rules

Alert rules are defined as a `PrometheusRule` CRD in `monitoring/prometheus/alerts.yaml`:

```bash
kubectl apply -f monitoring/prometheus/alerts.yaml
```

The rules are picked up by Prometheus automatically via the `release: prometheus-stack` label selector. See [Alerts](alerts.md) for a full explanation of each rule.

## Upgrading or uninstalling

```bash
# Upgrade with new values
helm upgrade prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values monitoring/prometheus/values.yaml

# Uninstall
helm uninstall prometheus-stack -n monitoring
```
