# Grafana

## Deployment

Grafana is deployed as part of the `kube-prometheus-stack` Helm chart — it's not a separate install. The `values.yaml` enables and configures it:

```yaml
grafana:
  enabled: true
  adminPassword: admin123
  service:
    type: ClusterIP
```

It runs in the `monitoring` namespace alongside Prometheus.

## Accessing Grafana

Grafana is a ClusterIP service, so you access it via port-forward:

```bash
kubectl port-forward svc/prometheus-stack-grafana \
  3000:80 -n monitoring &

open http://localhost:3000
```

Login credentials:
- **Username:** `admin`
- **Password:** `admin123`

## Data sources

### Prometheus

Grafana is pre-configured to connect to Prometheus at `http://prometheus-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090`. This is set up automatically by the Helm chart.

### Loki

The Loki datasource is configured via `monitoring/grafana/loki-datasource.yaml` — a ConfigMap with the `grafana_datasource: "1"` label that Grafana's sidecar picks up automatically:

```yaml
datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: false
    jsonData:
      maxLines: 1000
      derivedFields:
        - name: TraceID
          matcherRegex: "trace_id=(\\w+)"
          url: ""
```

Apply it:
```bash
kubectl apply -f monitoring/grafana/loki-datasource.yaml
```

## Dashboards

### URLSnip Overview (auto-provisioned)

The `values.yaml` provisions a dashboard named "URLSnip Overview" in the "URLSnip" folder automatically on install. It contains three panels:

| Panel | Query | Type |
|---|---|---|
| Request Rate | `rate(http_requests_total[1m])` | Time series graph |
| Request Latency p99 | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` | Time series graph |
| Error Rate | `rate(http_requests_total{status=~'5..'}[1m])` | Time series graph |

### Kubernetes dashboards

The `kube-prometheus-stack` also ships a full set of pre-built dashboards for:
- Kubernetes cluster overview
- Node resource usage
- Pod CPU and memory
- Persistent volumes
- API server latency

These are accessible in the "Default" folder in Grafana.

## Querying urlsnip metrics manually

In Grafana's Explore view (the compass icon), select the Prometheus data source and use these queries:

```promql
# Per-service request rate
rate(http_requests_total{job=~"urlsnip.*"}[1m])

# p99 latency for redirects only
histogram_quantile(0.99,
  rate(http_request_duration_seconds_bucket{job="urlsnip-redirect"}[5m])
)

# 5xx error rate
rate(http_requests_total{job=~"urlsnip.*", status=~"5.."}[5m])

# Pod CPU for urlsnip namespace
sum by (pod) (
  rate(container_cpu_usage_seconds_total{namespace="urlsnip", container!=""}[5m])
)

# HPA replicas
kube_horizontalpodautoscaler_status_current_replicas{namespace="urlsnip"}
```

## Querying logs in Grafana (LogQL)

Switch data source to Loki in the Explore view:

```logql
# All logs from urlsnip namespace
{namespace="urlsnip"}

# Shortener logs only
{namespace="urlsnip", app="shortener"}

# Filter for errors
{namespace="urlsnip"} |= "ERROR"

# Filter for a specific short code
{namespace="urlsnip"} |= "aB3xYz"
```

See [Loki](loki.md) for more LogQL examples.

## Viewing active alerts

In Grafana, go to **Alerting → Alert Rules**. Active alerts (HighErrorRate, HighLatency, PodNotReady, HPAMaxedOut) will show here when firing.

Alternatively, view alert state directly in Prometheus:
```bash
# In Prometheus UI at http://localhost:9090
# Navigate to Alerts tab
```

## Restarting or upgrading Grafana

Grafana is managed by the Helm release. To apply changes to `values.yaml`:

```bash
helm upgrade prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values monitoring/prometheus/values.yaml
```

If Grafana's pod is stuck or the dashboard isn't showing:

```bash
kubectl rollout restart deployment/prometheus-stack-grafana -n monitoring
kubectl logs deployment/prometheus-stack-grafana -n monitoring
```
