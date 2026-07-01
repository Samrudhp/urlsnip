# Alerts

Alert rules are defined in `monitoring/prometheus/alerts.yaml` as a `PrometheusRule` CRD. They live in the `monitoring` namespace and are picked up by the Prometheus operator via the `release: prometheus-stack` label.

Apply them:
```bash
kubectl apply -f monitoring/prometheus/alerts.yaml
```

There are four rules, all in the `urlsnip.rules` group.

---

## HighErrorRate

```yaml
alert: HighErrorRate
expr: |
  rate(http_requests_total{status=~"5.."}[5m]) > 0.05
for: 2m
labels:
  severity: warning
annotations:
  summary: "High error rate on {{ $labels.job }}"
  description: "Error rate is {{ $value }} req/s"
```

**What it means:** More than 0.05 requests per second are returning 5xx status codes, sustained for 2 minutes. At a low request rate (e.g. 1 req/s) this fires if even 1 in 20 requests fails. At higher rates the threshold becomes proportionally less sensitive.

**Common causes:**
- A service pod is restarting (CrashLoopBackOff)
- DynamoDB connection to Floci is failing — check `172.21.0.2:4566` is reachable from pods
- Redis is down — redirect and shortener both depend on it
- A code bug introduced in a recent deploy

**What to do:**
1. Check which job is firing: the `{{ $labels.job }}` in the summary tells you (urlsnip-shortener, urlsnip-redirect, or urlsnip-analytics)
2. Check pod logs:
   ```bash
   kubectl logs -n urlsnip deployment/<service> --tail=50
   ```
3. Check pod status:
   ```bash
   kubectl get pods -n urlsnip
   kubectl describe pod <pod-name> -n urlsnip
   ```
4. Check if Floci is reachable:
   ```bash
   curl http://localhost:4566/_floci/health
   ```
5. If a recent deploy caused it, roll back:
   ```bash
   kubectl rollout undo deployment/<service> -n urlsnip
   ```

---

## HighLatency

```yaml
alert: HighLatency
expr: |
  histogram_quantile(0.99,
    rate(http_request_duration_seconds_bucket[5m])
  ) > 1.0
for: 2m
labels:
  severity: warning
annotations:
  summary: "High p99 latency on {{ $labels.job }}"
  description: "p99 latency is {{ $value }}s"
```

**What it means:** The 99th percentile request duration exceeds 1 second, sustained for 2 minutes. At least 1% of requests are taking longer than 1 second to respond.

**Common causes:**
- Redis cache is cold (all requests falling back to DynamoDB) — a Redis restart causes this temporarily
- Floci is slow — can happen if the Mac is under heavy load, Docker is resource-constrained, or Floci is initializing after a restart
- A pod is under memory pressure and GC-pausing
- The HPA hasn't scaled fast enough yet during a traffic spike

**What to do:**
1. Check the p99 in Prometheus/Grafana:
   ```promql
   histogram_quantile(0.99,
     rate(http_request_duration_seconds_bucket{job="urlsnip-redirect"}[5m])
   )
   ```
2. Check Redis health:
   ```bash
   kubectl exec -n urlsnip deployment/shortener -- \
     python3 -c "import redis, os; r=redis.Redis(host=os.getenv('REDIS_HOST','redis-service')); print(r.ping())"
   ```
3. Check Floci latency:
   ```bash
   time curl -s http://localhost:4566/_floci/health
   ```
4. Check HPA status — if at max replicas, the alert will fire together with HPAMaxedOut:
   ```bash
   kubectl get hpa -n urlsnip
   ```
5. Check Docker Desktop resource limits (CPU/memory) and increase if constrained.

---

## PodNotReady

```yaml
alert: PodNotReady
expr: |
  kube_pod_status_ready{namespace="urlsnip", condition="true"} == 0
for: 1m
labels:
  severity: critical
annotations:
  summary: "Pod not ready in urlsnip namespace"
  description: "Pod {{ $labels.pod }} is not ready"
```

**What it means:** A pod in the `urlsnip` namespace has been in a non-Ready state for more than 1 minute. This is `severity: critical` — it means traffic is not being served by that pod.

**Common causes:**
- The readiness probe (`GET /health`) is failing — the service can't start due to a bad env var or a dependency being down
- The pod is in `CrashLoopBackOff` — the container is crashing on startup
- The pod is in `Pending` — no node resources available or image can't be pulled
- A bad image was deployed — see the Events in `kubectl describe`

**What to do:**
1. Identify which pod:
   ```bash
   kubectl get pods -n urlsnip
   ```
2. Check events:
   ```bash
   kubectl describe pod <pod-name> -n urlsnip
   ```
3. Check logs (even for a crashing pod, logs from the last attempt are kept):
   ```bash
   kubectl logs <pod-name> -n urlsnip --previous
   ```
4. Common fixes:
   - Image pull failure: verify `ghcr-secret` exists and is valid, verify the image tag exists in ghcr.io
   - Config error: check the ConfigMap values are correct, especially `AWS_ENDPOINT_URL` and `REDIS_HOST`
   - Dependency down: verify Floci and Redis are running

---

## HPAMaxedOut

```yaml
alert: HPAMaxedOut
expr: |
  kube_horizontalpodautoscaler_status_current_replicas{namespace="urlsnip"}
  ==
  kube_horizontalpodautoscaler_spec_max_replicas{namespace="urlsnip"}
for: 5m
labels:
  severity: warning
annotations:
  summary: "HPA {{ $labels.horizontalpodautoscaler }} at max replicas"
```

**What it means:** An HPA has been at its maximum replica count for 5 consecutive minutes. The HPA wants to scale further but can't — it's hitting the `maxReplicas` ceiling.

Max replicas by service:
- shortener-hpa: 5
- redirect-hpa: 10
- analytics-hpa: 3

**Common causes:**
- Sustained high traffic — the redirect service is getting more hits than 10 pods can handle
- A runaway loop — something is sending requests in a loop, driving CPU up
- Resource limits are too low — the pods are CPU-throttled at their limit, causing the HPA to see high utilization even at max scale

**What to do:**
1. Check which HPA is maxed:
   ```bash
   kubectl get hpa -n urlsnip
   ```
2. Temporarily increase `maxReplicas` in the HPA manifest and reapply:
   ```bash
   kubectl edit hpa redirect-hpa -n urlsnip
   # Change maxReplicas: 10 to maxReplicas: 15
   ```
3. Check CPU limits — if pods are consistently near their `250m` CPU limit, increase the limit in the deployment manifest
4. Check if there's an unusual traffic pattern:
   ```promql
   rate(http_requests_total{job="urlsnip-redirect"}[1m])
   ```
5. On a local Mac, Docker Desktop's CPU allocation limits how much the k3s cluster can actually use. If this fires regularly, increase Docker Desktop's CPU allocation in its settings.
