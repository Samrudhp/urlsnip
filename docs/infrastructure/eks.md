# EKS / k3s

## How Floci EKS works

Floci's EKS emulation doesn't mock the Kubernetes API — it runs real k3s inside a Docker container on your Mac. When you call `aws eks create-cluster`, Floci:

1. Pulls and starts a k3s Docker container named `floci-eks-urlsnip-cluster`
2. Waits for k3s to be ready
3. Generates a kubeconfig pointing to `https://127.0.0.1:6500`
4. Returns the cluster as `ACTIVE`

The result is a real, functional single-node Kubernetes cluster. All `kubectl` commands, `helm install`, and `kubectl apply` work exactly as they would against a real EKS cluster.

## Creating the cluster

Floci must be running before you create the cluster:

```bash
# Ensure Floci is up
curl http://localhost:4566/_floci/health

# Create the EKS cluster (~60 seconds)
aws eks create-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1

# Poll until ACTIVE
aws eks describe-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --query "cluster.status" \
  --output text
# ACTIVE
```

## Getting kubeconfig

```bash
aws eks update-kubeconfig \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1 \
  --kubeconfig ~/.kube/urlsnip-local

export KUBECONFIG=~/.kube/urlsnip-local

# Verify
kubectl cluster-info
# Kubernetes control plane is running at https://127.0.0.1:6500
```

Port 6500 is where Floci exposes the k3s API server. This is not configurable — Floci always uses 6500 for EKS clusters. The default k8s port (6443) is not used.

## Cluster name

The Docker container is named `floci-eks-urlsnip-cluster`. This name is derived from the cluster name you passed to `create-cluster`. The CD pipeline uses this container name to `docker cp` image tars into it.

```bash
docker ps | grep floci-eks
# floci-eks-urlsnip-cluster   k3s:latest   ...   Up 2 hours
```

## Networking: how pods reach Floci

Pods inside k3s need to reach Floci's AWS APIs. The pods can't use `localhost:4566` because that refers to each pod's own network namespace.

Floci runs on the Docker bridge network. Its IP on that network is typically `172.21.0.2`. This IP is stable as long as you don't recreate the Floci container.

The `urlsnip-config` ConfigMap hardcodes this IP:

```yaml
data:
  AWS_ENDPOINT_URL: "http://172.21.0.2:4566"
  SQS_QUEUE_URL: "http://172.21.0.2:4566/000000000000/urlsnip-events"
```

To find the current IP:

```bash
docker inspect floci \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

If you ever see `Connection refused` or `Unable to connect to endpoint` errors in pod logs when connecting to AWS, the Floci IP has likely changed. Update the ConfigMap and restart deployments.

**Note on host.k3d.internal:** You may see references to `host.k3d.internal` as an alternative way to reach the host from inside k3s pods. This hostname does not resolve reliably in the Floci k3s environment — use the explicit bridge IP `172.21.0.2` instead.

## imagePullPolicy and image loading

The deployment manifests use `imagePullPolicy: Always`. This means k3s will always attempt to pull the image from `ghcr.io` when starting a pod. For this to work:

1. The `ghcr-secret` image pull secret must exist in the `urlsnip` namespace
2. The image must be pushed to `ghcr.io` (the CI pipeline does this)

For local development without going through the CI pipeline, you can load images directly into k3s containerd using `ctr images import` (see [Kubernetes setup](../setup/kubernetes.md)).

## Node and cluster info

```bash
# Node status
kubectl get nodes
# NAME                          STATUS   ROLES                  AGE
# floci-eks-urlsnip-cluster     Ready    control-plane,master   1d

# Cluster version
kubectl version
# Server Version: v1.34.x+k3s1

# All resources in urlsnip namespace
kubectl get all -n urlsnip

# Describe a pod
kubectl describe pod <pod-name> -n urlsnip

# Exec into a pod
kubectl exec -it <pod-name> -n urlsnip -- bash
```

## Deleting and recreating the cluster

```bash
# Delete the cluster
aws eks delete-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566

# This stops and removes the floci-eks-urlsnip-cluster container
# All deployments, pods, and state are lost

# Recreate
aws eks create-cluster \
  --name urlsnip-cluster \
  --endpoint-url http://localhost:4566 \
  --region us-east-1
```

After recreating, you need to:
1. Update kubeconfig: `aws eks update-kubeconfig ...`
2. Create `ghcr-secret`
3. Reapply all manifests
4. Reload images into containerd
