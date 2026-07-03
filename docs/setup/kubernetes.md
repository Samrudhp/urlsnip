# Kubernetes setup

urlsnip runs on a real k3s cluster managed by Floci's EKS emulation. The cluster runs inside a Docker container named `floci-eks-urlsnip-cluster`.

## Start the Floci EKS cluster

```bash
# Make sure Floci is running (it can run standalone, separate from docker-compose)
docker run -d \
  --name floci \
  -p 4566:4566 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  floci/floci:latest

# Create the EKS cluster (this takes ~60 seconds — it starts a real k3s container)
aws eks create-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1

# Wait for it to show ACTIVE
aws eks describe-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --query "cluster.status"
# "ACTIVE"
```

## Get the kubeconfig

```bash
aws eks update-kubeconfig \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1 \
  --kubeconfig ~/.kube/urlsnip-local

export KUBECONFIG=~/.kube/urlsnip-local

# Verify the cluster is reachable
kubectl cluster-info
# Kubernetes control plane is running at https://127.0.0.1:6500
```

Important: the kubeconfig points to `https://127.0.0.1:6500`, not the standard 6443. Floci maps k3s's API server to port 6500. If you ever see connection refused errors on port 6443, your KUBECONFIG is pointing at the wrong file.

## Create the GHCR image pull secret

Before applying manifests, pods need credentials to pull from `ghcr.io`:

```bash
export GITHUB_USER=your-username
export GITHUB_TOKEN=ghp_your_personal_access_token

bash scripts/create-ghcr-secret.sh
```

## Apply all Kubernetes manifests

```bash
# Apply in order: namespace first, then everything else
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml

# Shortener
kubectl apply -f k8s/shortener/deployment.yaml
kubectl apply -f k8s/shortener/service.yaml
kubectl apply -f k8s/shortener/hpa.yaml

# Redirect
kubectl apply -f k8s/redirect/deployment.yaml
kubectl apply -f k8s/redirect/service.yaml
kubectl apply -f k8s/redirect/hpa.yaml

# Analytics
kubectl apply -f k8s/analytics/deployment.yaml
kubectl apply -f k8s/analytics/service.yaml
kubectl apply -f k8s/analytics/hpa.yaml
```

Or apply all k8s files at once (order matters for namespace, so apply namespace first):

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/ --recursive
```

## Loading images into k3s

k3s uses containerd, not Docker. Images built with `docker build` are not automatically available inside k3s. You must import them:

```bash
# Build the image
docker build --platform linux/arm64 \
  -t ghcr.io/OWNER/urlsnip-shortener:latest \
  services/shortener-service/

# Save to tar
docker save ghcr.io/OWNER/urlsnip-shortener:latest \
  -o /tmp/urlsnip-shortener.tar

# Copy into the k3s container
docker cp /tmp/urlsnip-shortener.tar \
  floci-eks-urlsnip-cluster:/tmp/urlsnip-shortener.tar

# Import into containerd
docker exec floci-eks-urlsnip-cluster \
  ctr images import /tmp/urlsnip-shortener.tar

# Repeat for redirect and analytics
```

This is the same process the CD pipeline automates. You only need to do this manually when the CD pipeline hasn't run yet (e.g. first-time setup).

## Verify pods are running

```bash
kubectl get pods -n urlsnip
# NAME                         READY   STATUS    RESTARTS   AGE
# shortener-xxx-yyy            1/1     Running   0          2m
# shortener-xxx-zzz            1/1     Running   0          2m
# redirect-xxx-aaa             1/1     Running   0          2m
# redirect-xxx-bbb             1/1     Running   0          2m
# analytics-xxx-ccc            1/1     Running   0          2m

kubectl get hpa -n urlsnip
# NAME            REFERENCE              TARGETS   MINPODS   MAXPODS   REPLICAS
# shortener-hpa   Deployment/shortener   5%/50%    2         5         2
# redirect-hpa    Deployment/redirect    5%/50%    2         10        2
# analytics-hpa   Deployment/analytics   5%/60%    1         3         1
```

## Port-forward and test

```bash
# Shortener (background)
kubectl port-forward svc/shortener-service 8000:8000 -n urlsnip &

# Redirect (background)
kubectl port-forward svc/redirect-service 8001:8001 -n urlsnip &

# Analytics (background)
kubectl port-forward svc/analytics-service 8002:8002 -n urlsnip &

# Test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://kubernetes.io"}'
```

## Restore after Mac restart

After a Mac restart, the k3s container stops. To bring everything back:

```bash
# 1. Start Docker Desktop
# 2. Check if the k3s container is stopped (not removed)
docker ps -a | grep floci-eks-urlsnip-cluster

# 3. Start it
docker start floci-eks-urlsnip-cluster

# 4. Start Floci (if it was also stopped)
docker start floci

# 5. Set KUBECONFIG
export KUBECONFIG=~/.kube/urlsnip-local

# 6. Check the cluster
kubectl get nodes
kubectl get pods -n urlsnip

# If pods are in CrashLoopBackOff, check if Floci is healthy first:
curl http://localhost:4566/_floci/health

# Then check pod logs:
kubectl logs -n urlsnip deployment/shortener
```

Pods should come back on their own once the cluster is running. If they stay in Pending, check that the node is Ready:

```bash
kubectl get nodes
# NAME                STATUS   ROLES                  AGE
# floci-eks-...       Ready    control-plane,master   1d
```
