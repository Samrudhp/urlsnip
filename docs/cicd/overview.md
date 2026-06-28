# CI/CD overview

## Architecture

```
Push to main / PR to main
        │
        ▼
  ci.yml workflow
  ┌─────────────────────────────────────┐
  │  Job: test                          │
  │  - pytest + import check (x3)       │
  │           │                         │
  │           ▼                         │
  │  Job: build-and-push                │
  │  - docker buildx (linux/arm64)      │
  │  - push to ghcr.io/OWNER/:sha       │
  │                                     │
  │  Job: terraform-validate (parallel) │
  │  - terraform init + validate + plan │
  └─────────────────────────────────────┘
        │ on success
        ▼
  cd.yml workflow (workflow_run trigger)
  ┌─────────────────────────────────────┐
  │  Job: deploy                        │
  │  - pull 3 images from ghcr.io       │
  │  - docker save → tar files          │
  │  - docker cp → k3s container        │
  │  - ctr images import (x3)           │
  │  - kubectl set image (x3)           │
  │  - kubectl rollout status (x3)      │
  │  - curl health checks via pf (x3)   │
  └─────────────────────────────────────┘
```

## Where it runs

Everything runs on a **self-hosted GitHub Actions runner** on your Mac M4. The runner process (`actions-runner/run.sh`) runs as a launchd service so it starts automatically on Mac boot.

The runner has:
- Direct access to Docker daemon
- Direct access to `localhost:4566` (Floci)
- `KUBECONFIG=~/.kube/urlsnip-local` pointing at the k3s cluster
- `kubectl` and `helm` on PATH

## Why self-hosted

Cloud runners (GitHub's `ubuntu-latest`) run in isolated VMs with no access to your local network. The entire CI/CD pipeline depends on things that only exist on your Mac:

| Dependency | Why cloud runner can't access it |
|---|---|
| `localhost:4566` (Floci) | Runs on your Mac |
| `~/.kube/urlsnip-local` | kubeconfig for your local k3s |
| `floci-eks-urlsnip-cluster` Docker container | Runs on your Mac's Docker daemon |
| `docker cp` into k3s | Requires access to local Docker socket |

## Image tagging strategy

Every image is tagged with the full 40-character git commit SHA (`${{ github.sha }}`):

```
ghcr.io/OWNER/urlsnip-shortener:a1b2c3d4e5f6...
ghcr.io/OWNER/urlsnip-redirect:a1b2c3d4e5f6...
ghcr.io/OWNER/urlsnip-analytics:a1b2c3d4e5f6...
```

A `latest` tag is also pushed simultaneously.

**Why SHA tagging:**
- Every build is uniquely identifiable and traceable to a specific commit
- Rollback is deterministic: `kubectl set image deployment/shortener shortener=ghcr.io/OWNER/urlsnip-shortener:<previous-sha>`
- No ambiguity about what's running in the cluster — `kubectl describe pod` shows the exact SHA

The CD workflow resolves the SHA from `github.event.workflow_run.head_sha` — the SHA of the commit that triggered the upstream CI run. This ensures CI and CD always operate on the same commit.

## ghcr.io (GitHub Container Registry)

Images are stored at `ghcr.io/OWNER/urlsnip-{shortener,redirect,analytics}`.

Access is controlled by `secrets.GITHUB_TOKEN` which is automatically injected into every GitHub Actions workflow — no manual token setup needed for CI. For the Kubernetes cluster to pull images, a `ghcr-secret` image pull secret is created manually once (see [create-ghcr-secret.sh](../../scripts/create-ghcr-secret.sh)).

Image visibility follows the GitHub repository visibility. If your repo is private, images are private by default.

## Secrets used

| Secret | Where it comes from | Used for |
|---|---|---|
| `secrets.GITHUB_TOKEN` | Auto-injected by GitHub Actions | ghcr.io login for push (CI) and pull (CD) |

No other secrets are needed. AWS credentials are hardcoded as `test/test` (Floci accepts any non-empty value). The kubeconfig is on the runner's filesystem.

## Trigger conditions

**ci.yml triggers:**
- `push` to `main`
- `pull_request` targeting `main`

**cd.yml triggers:**
- `workflow_run` of `ci.yml` completing with `conclusion == success`, on `main` branch only

This means PRs trigger CI but not CD. Only a successful merge to main triggers a deployment.
