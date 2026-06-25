# Design decisions

## Why FastAPI, not Flask or Django?

FastAPI has native async support, automatic OpenAPI docs at `/docs`, and Pydantic model validation built in. For microservices where each service has 2-4 endpoints and needs to be lightweight, it's a better fit than Django (which is a full-stack framework with ORM, admin, and a lot of weight we don't need). Flask is fine but requires separate libraries for everything FastAPI gives you out of the box. The `prometheus-fastapi-instrumentator` library integrates with FastAPI's middleware system with a one-liner, which was a deciding factor for observability.

## Why DynamoDB, not Postgres or MongoDB?

Short link lookups are single-item reads by primary key (`code`). DynamoDB is purpose-built for exactly this access pattern — sub-millisecond get_item by hash key at any scale. There's no schema migration to manage, no connection pool to tune. The `clicks` counter increments atomically via `ADD` in `update_item` without needing a transaction. Since we're using Floci locally, we also get the DynamoDB API without running a full relational database. If we ever move to production AWS, the same Terraform and boto3 code works unchanged.

## Why SQS for analytics, not a direct DynamoDB write from the redirect service?

Two reasons:

**Decoupling:** The redirect service's only job is to be fast. If it had to write a click event to DynamoDB on every redirect, a DynamoDB slowdown or outage would block the redirect response. With SQS, the redirect returns a 302 in microseconds and the click count update happens asynchronously. The redirect service doesn't even have a boto3 DynamoDB client.

**Backpressure:** SQS naturally buffers bursts. If 10,000 redirects happen in a second, the analytics service processes them at its own pace without being overwhelmed. Messages sit safely in the queue (retention: 24 hours) until processed.

The current implementation actually publishes the SQS event from the shortener (on link creation), not from the redirect service on each hit. This is a simplification — extending it to publish from the redirect service would require adding an SQS client to that service.

## Why Redis as a cache layer?

DynamoDB with PAY_PER_REQUEST billing charges per read. For a URL shortener, the same popular short codes will be hit thousands of times. Caching them in Redis with a 1-hour TTL means the first hit after expiry hits DynamoDB, and subsequent hits are free and ~0.1ms latency. Redis also gives the redirect service a way to serve responses without making any AWS API call at all on hot paths.

## Why k3s via Floci, not minikube or kind?

minikube and kind are great for testing Kubernetes manifests but they're not representative of a real EKS-style cluster. Floci's EKS emulation runs actual k3s inside a Docker container and exposes a real kubeconfig pointing to a real API server. The networking — where pods use a Docker bridge IP (`172.21.0.2`) to reach Floci's AWS services — is the same topology you'd have with EKS pods reaching real AWS endpoints. This means the ConfigMap values, the service discovery, and the HPA behavior are all as close to production as possible on a local Mac.

The container is named `floci-eks-urlsnip-cluster`. The kubeconfig is written to `~/.kube/urlsnip-local` and points to `https://127.0.0.1:6500` (Floci maps the k3s API server to port 6500 on localhost, not the default 6443).

## Why a self-hosted GitHub Actions runner, not a cloud runner?

Cloud runners (ubuntu-latest) run in GitHub's infrastructure and can't reach `localhost:4566`. The entire project depends on Floci running on the local Mac at that address. The self-hosted runner runs on the same Mac, so:

- The test job can reach Floci for any integration tests
- The terraform-validate job can plan against a live Floci instance
- The CD job can `docker cp` into the `floci-eks-urlsnip-cluster` container and call `kubectl` with the local kubeconfig

There's no viable way to run this CI/CD pipeline on a cloud runner without either mocking all AWS calls or standing up real cloud infrastructure.

## Why ghcr.io, not DockerHub or ECR?

**vs DockerHub:** ghcr.io is tightly integrated with GitHub Actions — `secrets.GITHUB_TOKEN` is automatically available in every workflow and grants push/pull access to the repo's packages. No extra credentials to manage.

**vs ECR:** ECR would require real AWS IAM credentials and a real AWS account. Since the project deliberately uses Floci to avoid real AWS costs and complexity, pulling images from ECR (even a local ECR emulation) adds unnecessary friction. ghcr.io is accessible from anywhere with internet access, including the self-hosted runner.

Image tags use the full git commit SHA (`github.sha`). This means every build is traceable to the exact commit that produced it, and rollbacks are a `kubectl set image` command pointing to the previous SHA.
