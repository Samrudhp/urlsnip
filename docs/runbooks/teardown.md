# Teardown runbook

How to stop everything cleanly. Do this in reverse order of startup.

---

## Kill active port-forwards first

Port-forward processes run in the background and don't stop with the cluster. Find and kill them:

```bash
# List all kubectl port-forward processes
ps aux | grep "kubectl port-forward" | grep -v grep

# Kill them all at once
pkill -f "kubectl port-forward"

# Or kill individually by PID
kill <PID>
```

Verify they're gone:
```bash
ps aux | grep "kubectl port-forward" | grep -v grep
# (no output)
```

---

## Stop observability stack

```bash
# Uninstall Loki and Promtail
helm uninstall promtail -n monitoring
helm uninstall loki -n monitoring

# Uninstall Prometheus + Grafana
helm uninstall prometheus-stack -n monitoring

# Remove alert rules and Loki datasource configmap
kubectl delete -f monitoring/prometheus/alerts.yaml --ignore-not-found
kubectl delete -f monitoring/grafana/loki-datasource.yaml --ignore-not-found

# Optionally remove the monitoring namespace entirely
kubectl delete namespace monitoring
```

---

## Stop urlsnip Kubernetes workloads

```bash
# Remove deployments, services, HPAs (reverse order is fine)
kubectl delete -f k8s/analytics/ --ignore-not-found
kubectl delete -f k8s/redirect/  --ignore-not-found
kubectl delete -f k8s/shortener/ --ignore-not-found
kubectl delete -f k8s/configmap.yaml --ignore-not-found

# Or delete everything in the namespace at once
kubectl delete namespace urlsnip

# Note: deleting the namespace removes everything in it (pods, services,
# HPAs, secrets, configmaps) but does NOT remove the Floci resources
# (DynamoDB table, SQS queue, S3 bucket — those are managed by Terraform)
```

---

## Stop the k3s cluster

You can either stop the container (preserves it for next time) or delete it entirely.

### Stop (preserves state, faster restart next time)

```bash
docker stop floci-eks-urlsnip-cluster
```

### Delete entirely (clean slate next time)

```bash
aws eks delete-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1

# Verify the container is gone
docker ps -a | grep floci-eks-urlsnip-cluster
# (no output)
```

If you delete the cluster, next startup requires `aws eks create-cluster` again (~60 seconds) and re-applying all manifests.

---

## Destroy Terraform-managed AWS resources

```bash
cd /path/to/urlsnip/terraform

terraform destroy
# Review the plan — it will show destroying:
# - aws_dynamodb_table.urlsnip
# - aws_sqs_queue.urlsnip_events
# - aws_s3_bucket.backups
# - aws_s3_bucket_versioning.backups

# Type "yes" to confirm
```

This removes all data in DynamoDB and SQS. All shortened URLs are gone.

If you want to preserve the data, don't run `terraform destroy` — just stop Floci. With `FLOCI_STORAGE_MODE=hybrid`, data persists in the container between restarts.

---

## Stop Floci

### If started with Docker Compose

```bash
cd /path/to/urlsnip
docker compose down

# To also remove the Redis volume (clears all cached data):
docker compose down -v
```

### If started standalone

```bash
docker stop floci

# To remove the container (loses hybrid storage state):
docker rm floci
```

---

## Stop the GitHub Actions runner

The runner is a launchd service that starts automatically. If you want to stop it temporarily:

```bash
cd ~/actions-runner
./svc.sh stop
```

To stop permanently and unregister:

```bash
cd ~/actions-runner
./svc.sh stop
./svc.sh uninstall
./config.sh remove --token <RUNNER_REMOVAL_TOKEN>
# Get the removal token from GitHub: Settings → Actions → Runners → click runner → Remove
```

---

## Clean up Docker resources

After teardown you may have dangling images and containers:

```bash
# Remove stopped containers
docker container prune -f

# Remove unused images (including urlsnip service images)
docker image prune -f

# Remove all urlsnip images specifically
docker images | grep urlsnip | awk '{print $3}' | xargs docker rmi -f

# Remove all ghcr.io urlsnip images
docker images | grep ghcr.io | grep urlsnip | awk '{print $3}' | xargs docker rmi -f

# Full system prune (removes everything not currently used — careful)
docker system prune -f
```

---

## Teardown order summary

| Step | Command | Data lost? |
|---|---|---|
| Kill port-forwards | `pkill -f "kubectl port-forward"` | No |
| Uninstall observability | `helm uninstall ...` | Metrics history |
| Delete k8s workloads | `kubectl delete namespace urlsnip` | Pod state only |
| Stop k3s cluster | `docker stop floci-eks-urlsnip-cluster` | No |
| Terraform destroy | `terraform destroy` | All DynamoDB + SQS data |
| Stop Floci | `docker stop floci` | No (hybrid storage) |
| Stop runner | `./svc.sh stop` | No |
