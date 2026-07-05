# Troubleshooting

Real errors encountered while building and running urlsnip, with exact fixes.

---

## KUBECONFIG pointing to the wrong port (6443 vs 6500)

**Symptom:**
```
E0621 12:34:56.789012   12345 memcache.go:265] couldn't get current server API group list:
Get "https://127.0.0.1:6443/api?timeout=32s": dial tcp 127.0.0.1:6443: connect: connection refused
```

**Cause:** Your `KUBECONFIG` is pointing at a different config file (e.g. `~/.kube/config`) that has an old cluster entry using port 6443. Floci's k3s API server runs on port **6500**, not 6443.

**Fix:**
```bash
# Override KUBECONFIG in your current shell
export KUBECONFIG=~/.kube/urlsnip-local

# Verify the server address in the kubeconfig
kubectl config view | grep server
# server: https://127.0.0.1:6500  ← this is correct

# Make it permanent
echo 'export KUBECONFIG=~/.kube/urlsnip-local' >> ~/.zshrc
source ~/.zshrc
```

If `~/.kube/urlsnip-local` doesn't exist, re-run:
```bash
aws eks update-kubeconfig \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1 \
  --kubeconfig ~/.kube/urlsnip-local
```

---

## AWS NoCredentialsError / Unable to locate credentials

**Symptom:**
```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```
or
```
An error occurred (InvalidClientTokenId) when calling the ListTables operation
```

**Cause:** The `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables are not set. Floci accepts any non-empty credentials, but they must be present.

**Fix:**
```bash
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566
```

Add to `~/.zshrc` so it persists:
```bash
cat >> ~/.zshrc << 'EOF'
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566
EOF
source ~/.zshrc
```

If the error is in a Python service rather than the CLI, verify the service's environment variables. In Docker Compose, check that `AWS_ACCESS_KEY_ID` is in the service's `environment:` block. In Kubernetes, verify the `urlsnip-config` ConfigMap is applied and the pod's `envFrom` references it:

```bash
kubectl get configmap urlsnip-config -n urlsnip -o yaml
kubectl describe pod <pod-name> -n urlsnip | grep -A 10 "Environment"
```

---

## Port already in use

**Symptom:**
```
Error starting userland proxy: listen tcp4 0.0.0.0:8000: bind: address already in use
```
or with kubectl:
```
error: unable to listen on port 8000: unable to create listener: Error listen tcp4 127.0.0.1:8000: bind: address already in use
```

**Cause:** Something else is already bound to that port. Common culprits: a previous Docker Compose run that wasn't cleanly stopped, or a previous port-forward still running.

**Fix:**
```bash
# Find what's using the port
lsof -i :8000
lsof -i :8001
lsof -i :8002

# Kill it by PID
kill -9 <PID>

# Or kill all kubectl port-forwards at once
pkill -f "kubectl port-forward"

# Or kill the Docker container holding the port
docker compose down
```

If Docker Compose fails to start because port 4566 is in use:
```bash
lsof -i :4566
# If it's a stale Floci container:
docker stop $(docker ps -q --filter "publish=4566")
```

---

## Pod stuck in Pending

**Symptom:**
```bash
kubectl get pods -n urlsnip
# NAME               READY   STATUS    RESTARTS
# shortener-abc-xyz  0/1     Pending   0
```

```bash
kubectl describe pod shortener-abc-xyz -n urlsnip
# Events:
#   Warning  FailedScheduling  ... 0/1 nodes are available: 1 node(s) had untolerated taint
```
or
```
  Warning  Failed  ... Failed to pull image "ghcr.io/OWNER/urlsnip-shortener:latest": ...
            rpc error: code = NotFound desc = failed to pull and unpack image
```

**Cause 1: Node not ready** — the k3s container was stopped and hasn't fully initialized yet.

```bash
kubectl get nodes
# NAME                        STATUS     ROLES
# floci-eks-urlsnip-cluster   NotReady   control-plane,master

# Wait for it to become Ready (up to 2 minutes after docker start)
kubectl get nodes -w
```

**Cause 2: Image not found in containerd** — the image hasn't been imported yet.

```bash
# Verify image is in containerd
docker exec floci-eks-urlsnip-cluster ctr images list | grep urlsnip

# If missing, re-import
docker save ghcr.io/OWNER/urlsnip-shortener:latest -o /tmp/shortener.tar
docker cp /tmp/shortener.tar floci-eks-urlsnip-cluster:/tmp/shortener.tar
docker exec floci-eks-urlsnip-cluster ctr images import /tmp/shortener.tar
```

**Cause 3: `ghcr-secret` missing** — the pod can't pull from ghcr.io.

```bash
kubectl get secret ghcr-secret -n urlsnip
# Error from server (NotFound): secrets "ghcr-secret" not found

export GITHUB_USER=your-username
export GITHUB_TOKEN=ghp_your_token
bash scripts/create-ghcr-secret.sh
```

---

## Pod in CrashLoopBackOff

**Symptom:**
```bash
kubectl get pods -n urlsnip
# NAME               READY   STATUS             RESTARTS
# shortener-abc-xyz  0/1     CrashLoopBackOff   5
```

**Cause:** The container is starting and crashing repeatedly. Most common causes: bad env var, can't connect to a dependency, Python import error.

**Fix:**
```bash
# Read logs from the last crash
kubectl logs shortener-abc-xyz -n urlsnip --previous

# Read current logs
kubectl logs shortener-abc-xyz -n urlsnip

# Common log patterns and their fixes:

# "redis.exceptions.ConnectionError: Error connecting to localhost:6379"
# → REDIS_HOST is wrong. Should be "redis-service", not "localhost".
# Fix: kubectl get configmap urlsnip-config -n urlsnip -o yaml
# Verify REDIS_HOST: "redis-service"

# "botocore.exceptions.EndpointResolutionError: ... 172.21.0.2"
# → Floci IP in ConfigMap is wrong. Find the real IP:
docker inspect floci --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
# Update k8s/configmap.yaml and reapply:
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/shortener -n urlsnip

# "ModuleNotFoundError: No module named 'app'"
# → Python path issue in the Docker image. Rebuild the image.
```

---

## Port-forward died after pod restart

**Symptom:** A `kubectl port-forward` that was working stops responding after a pod was restarted or rescheduled. The terminal shows nothing, but curl hangs or returns connection refused.

**Cause:** `kubectl port-forward` is bound to a specific pod, not the service. When a pod is deleted and recreated, the port-forward tunnel breaks.

**Fix:** Always port-forward to the **Service**, not the pod:

```bash
# Wrong (breaks on pod restart):
kubectl port-forward pod/shortener-abc-xyz 8000:8000 -n urlsnip

# Right (survives pod restarts):
kubectl port-forward svc/shortener-service 8000:8000 -n urlsnip
```

If a service port-forward also died, kill it and restart:

```bash
pkill -f "kubectl port-forward svc/shortener-service"
kubectl port-forward svc/shortener-service 8000:8000 -n urlsnip &
```

---

## Floci not reachable from pods

**Symptom:** Services in Kubernetes log errors like:
```
botocore.exceptions.ConnectTimeoutError: Connect timeout on endpoint URL: "http://172.21.0.2:4566/..."
```
or
```
Failed to establish a new connection: [Errno 111] Connection refused
```

**Cause 1: The Floci container's IP has changed.** This happens when Floci is stopped and recreated — Docker may assign a different bridge IP.

```bash
# Get current Floci IP
docker inspect floci \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
# If it's not 172.21.0.2, update the ConfigMap:

kubectl edit configmap urlsnip-config -n urlsnip
# Change AWS_ENDPOINT_URL and SQS_QUEUE_URL to the new IP

kubectl rollout restart deployment/shortener deployment/redirect deployment/analytics -n urlsnip
```

**Cause 2: `host.k3d.internal` doesn't resolve.** If you see DNS resolution failures for `host.k3d.internal` in pod logs, this hostname is not reliable in the Floci k3s environment. Use the explicit Docker bridge IP instead (see above).

**Cause 3: Floci isn't running.** Check:
```bash
curl http://localhost:4566/_floci/health
docker ps | grep floci
```

---

## Images not found in k3s after deploy

**Symptom:** After running the CD pipeline, pods show `ErrImageNeverPull` or `ImagePullBackOff` even though images exist in ghcr.io.

**Cause 1: `imagePullPolicy: Never` is still set** — old manifests before the ghcr.io migration. The fix is to ensure `imagePullPolicy: Always` is in the deployment manifests. The current manifests already have this.

**Cause 2: `ctr images import` failed silently.** Check:

```bash
# List images in containerd
docker exec floci-eks-urlsnip-cluster ctr images list | grep urlsnip

# If missing, re-run the import manually
docker exec floci-eks-urlsnip-cluster ctr images import /tmp/urlsnip-shortener.tar
# Check for errors in the output
```

**Cause 3: `ghcr-secret` expired or doesn't exist.**

```bash
kubectl get secret ghcr-secret -n urlsnip
# If missing or you get 401 errors:
bash scripts/create-ghcr-secret.sh
kubectl rollout restart deployment/shortener deployment/redirect deployment/analytics -n urlsnip
```

---

## floci-init SQS token error (Docker Compose)

**Symptom:**
```
An error occurred (InvalidClientTokenId) when calling the CreateQueue operation:
The security token included in the request is invalid.
```

**Cause:** `floci-init` ran its AWS CLI commands before Floci was fully ready to accept requests, even though the health check passed. Floci's SQS endpoint occasionally takes a few extra seconds to initialize after the health check returns OK.

**Fix:**
```bash
# Simply restart the stack — floci-init will run again
docker compose down
docker compose up --build

# If it keeps failing, add a sleep before the aws commands.
# Edit docker-compose.yml, change the floci-init command to:
#   sleep 5 && aws dynamodb create-table ... && aws sqs create-queue ...
```

This is a race condition in Floci's startup. The `sleep 5` workaround is reliable.
