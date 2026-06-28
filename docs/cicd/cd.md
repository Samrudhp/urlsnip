# CD pipeline

File: `.github/workflows/cd.yml`

Triggered when the CI workflow completes successfully on `main`. All steps run in a single `deploy` job on `self-hosted`.

## Trigger

```yaml
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main]
```

The job only runs if `github.event.workflow_run.conclusion == 'success'`. A failed CI run does not trigger deployment.

## Resolving the commit SHA

```yaml
- name: Set image SHA
  id: sha
  run: |
    echo "sha=${{ github.event.workflow_run.head_sha }}" >> "$GITHUB_OUTPUT"
```

`workflow_run.head_sha` is the SHA of the commit in the CI run that triggered this deployment — not the SHA of the CD workflow's own trigger event. This ensures CI and CD always use the same commit and image tag.

All subsequent steps reference this as `${{ steps.sha.outputs.sha }}`.

---

## Step 1: Pull images from ghcr.io

```yaml
- name: Pull images
  run: |
    SHA=${{ steps.sha.outputs.sha }}
    docker pull ghcr.io/${{ github.repository_owner }}/urlsnip-shortener:${SHA}
    docker pull ghcr.io/${{ github.repository_owner }}/urlsnip-redirect:${SHA}
    docker pull ghcr.io/${{ github.repository_owner }}/urlsnip-analytics:${SHA}
```

This pulls the exact SHA-tagged images that CI built and pushed. If CI didn't push (e.g. build failed), these pulls fail and the deployment stops.

---

## Step 2: Save images to tar files

```yaml
- name: Save images to tar
  run: |
    SHA=${{ steps.sha.outputs.sha }}
    docker save ghcr.io/${{ github.repository_owner }}/urlsnip-shortener:${SHA} \
      -o /tmp/urlsnip-shortener.tar
    docker save ghcr.io/${{ github.repository_owner }}/urlsnip-redirect:${SHA} \
      -o /tmp/urlsnip-redirect.tar
    docker save ghcr.io/${{ github.repository_owner }}/urlsnip-analytics:${SHA} \
      -o /tmp/urlsnip-analytics.tar
```

`docker save` exports an image from the local Docker daemon to a tar archive. This is needed because the k3s cluster uses **containerd**, not Docker. containerd can't pull from the Docker daemon directly — the only bridge is the filesystem.

---

## Step 3: Copy tars into the k3s container

```yaml
- name: Copy tars into k3s container
  run: |
    docker cp /tmp/urlsnip-shortener.tar \
      floci-eks-urlsnip-cluster:/tmp/urlsnip-shortener.tar
    docker cp /tmp/urlsnip-redirect.tar \
      floci-eks-urlsnip-cluster:/tmp/urlsnip-redirect.tar
    docker cp /tmp/urlsnip-analytics.tar \
      floci-eks-urlsnip-cluster:/tmp/urlsnip-analytics.tar
```

`floci-eks-urlsnip-cluster` is the Docker container name of the k3s node. `docker cp` puts the tar files into the container's `/tmp/` directory, accessible by the containerd runtime inside.

---

## Step 4: Import images into containerd

```yaml
- name: Import images into containerd
  run: |
    docker exec floci-eks-urlsnip-cluster \
      ctr images import /tmp/urlsnip-shortener.tar
    docker exec floci-eks-urlsnip-cluster \
      ctr images import /tmp/urlsnip-redirect.tar
    docker exec floci-eks-urlsnip-cluster \
      ctr images import /tmp/urlsnip-analytics.tar
```

`ctr` is the containerd CLI available inside the k3s container. `ctr images import` loads the tar into containerd's image store, making the image available to Kubernetes pod scheduling.

After this step, running `docker exec floci-eks-urlsnip-cluster ctr images list` should show the newly imported images.

---

## Step 5: Update deployments (kubectl set image)

```yaml
- name: Update shortener deployment
  run: |
    SHA=${{ steps.sha.outputs.sha }}
    kubectl set image deployment/shortener \
      shortener=ghcr.io/${{ github.repository_owner }}/urlsnip-shortener:${SHA} \
      -n urlsnip
```

`kubectl set image deployment/shortener shortener=...` updates the container named `shortener` in the `shortener` deployment to use the new image tag. Kubernetes then starts a rolling update — new pods come up with the new image before old pods are terminated.

The same runs for `redirect` and `analytics`.

---

## Step 6: Wait for rollout

```yaml
- name: Wait for shortener rollout
  run: kubectl rollout status deployment/shortener -n urlsnip --timeout=120s
```

`kubectl rollout status` blocks until all pods in the rolling update are healthy (readiness probe passing) or the timeout is reached. With a 120-second timeout and 5-second readiness probe, up to 24 consecutive probe failures are tolerated before the step fails.

If this fails, the deployment is not complete — you should check pod logs and potentially roll back:

```bash
kubectl rollout undo deployment/shortener -n urlsnip
```

---

## Step 7: Health checks via port-forward

```yaml
- name: Health check shortener
  run: |
    kubectl port-forward svc/shortener-svc 18000:8000 -n urlsnip &
    PF_PID=$!
    sleep 3
    curl --fail --silent --max-time 10 http://localhost:18000/health | grep '"ok"'
    kill $PF_PID
```

After the rollout is confirmed, the pipeline does an end-to-end health check by:
1. Starting `kubectl port-forward` in the background
2. Waiting 3 seconds for it to establish
3. Curling `/health` and checking the response contains `"ok"`
4. Killing the port-forward process

If the curl fails (non-200 response or timeout), the step fails, surfacing a deployment problem that passed the readiness probe but failed the health endpoint logic.

The three services use ports 18000, 18001, 18002 for port-forwards to avoid conflicting with any existing port-forwards on 8000/8001/8002.

---

## Step 8: Cleanup

```yaml
- name: Cleanup tar files
  if: always()
  run: rm -f /tmp/urlsnip-shortener.tar /tmp/urlsnip-redirect.tar /tmp/urlsnip-analytics.tar
```

`if: always()` ensures cleanup runs even if an earlier step failed. Each tar is ~50-100MB, so leaving them around wastes disk space on the runner.

---

## Rollback procedure

If the deployment was successful but the new version has a bug:

```bash
# Roll back all three deployments to previous image
kubectl rollout undo deployment/shortener -n urlsnip
kubectl rollout undo deployment/redirect -n urlsnip
kubectl rollout undo deployment/analytics -n urlsnip

# Or roll back to a specific SHA
PREVIOUS_SHA=abc123def456...
kubectl set image deployment/shortener \
  shortener=ghcr.io/OWNER/urlsnip-shortener:${PREVIOUS_SHA} \
  -n urlsnip
kubectl rollout status deployment/shortener -n urlsnip
```
