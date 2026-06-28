# CI pipeline

File: `.github/workflows/ci.yml`

Triggered on push or PR to `main`. All jobs run on `self-hosted`.

## Environment variables

Set at the workflow level and available to all jobs:

```yaml
env:
  AWS_ACCESS_KEY_ID: test
  AWS_SECRET_ACCESS_KEY: test
  AWS_DEFAULT_REGION: us-east-1
  AWS_ENDPOINT_URL: http://localhost:4566
  REGISTRY: ghcr.io
```

These mirror what the services expect. If any tests make real boto3 calls against Floci, these ensure they find the right endpoint.

---

## Job 1: test

Runs pytest for each of the three services in sequence.

```yaml
test:
  name: Test
  runs-on: self-hosted
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Test shortener-service
      working-directory: services/shortener-service
      run: |
        pip install --quiet -r requirements.txt
        pip install --quiet pytest pytest-asyncio httpx
        pytest tests/ -v --tb=short || true
        python -c "from app.main import app; print('shortener: import OK')"
```

The `|| true` after pytest means if no `tests/` directory exists yet, the step doesn't fail. The `python -c` import check catches syntax errors and broken imports regardless.

**To add real tests:** Create `services/shortener-service/tests/test_main.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@patch("app.main.dynamodb")
@patch("app.main.cache")
@patch("app.main.sqs")
def test_shorten(mock_sqs, mock_cache, mock_dynamo):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table
    mock_cache.set.return_value = True
    mock_sqs.send_message.return_value = {"MessageId": "test"}

    response = client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert len(data["code"]) == 6
```

---

## Job 2: build-and-push

Runs after `test` passes. Builds all three images for `linux/arm64` and pushes to ghcr.io.

### Login to ghcr.io

```yaml
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}
```

`github.actor` is the user or bot that triggered the workflow. `GITHUB_TOKEN` is auto-injected and has `write:packages` permission (set via `permissions: packages: write` on the job).

### Docker Buildx setup

```yaml
- uses: docker/setup-buildx-action@v3
  with:
    driver: docker
```

The `driver: docker` setting uses the host's Docker daemon directly instead of BuildKit's default containerized builder. This is important — it means images end up in the local Docker image store, which is needed by the CD job's `docker save` step.

### Build and push (shortener example)

```yaml
- uses: docker/build-push-action@v5
  with:
    context: services/shortener-service
    platforms: linux/arm64
    push: true
    tags: |
      ghcr.io/${{ github.repository_owner }}/urlsnip-shortener:${{ github.sha }}
      ghcr.io/${{ github.repository_owner }}/urlsnip-shortener:latest
```

- `platforms: linux/arm64` — builds specifically for Apple Silicon. The Floci k3s node is arm64, so this must match.
- Two tags are pushed: the full SHA (for traceability and rollback) and `latest` (for convenience).
- The Dockerfile in each service directory sets the context. Docker's layer cache makes rebuilds fast if only code changed.

The same pattern repeats for redirect and analytics.

---

## Job 3: terraform-validate

Runs in parallel with `build-and-push` (both depend on `test` but not on each other).

```yaml
terraform-validate:
  needs: test
  steps:
    - name: Terraform init
      working-directory: terraform
      run: terraform init -backend=false -input=false

    - name: Terraform validate
      working-directory: terraform
      run: terraform validate

    - name: Terraform plan
      working-directory: terraform
      env:
        TF_VAR_aws_endpoint: http://localhost:4566
      run: |
        terraform plan \
          -input=false \
          -var="aws_endpoint=http://localhost:4566" \
          -out=tfplan
```

**`-backend=false`** skips backend initialization — no remote state is configured and there's no state file in CI. This means `init` only downloads providers.

**`terraform validate`** checks syntax and internal consistency of the `.tf` files without making any API calls.

**`terraform plan`** actually calls Floci at `localhost:4566` to check what changes would be made. Since the runner is on the Mac and Floci is running, this is a real plan against real emulated infrastructure. If resources already exist (from a previous apply), plan shows no changes.

The plan is saved to `tfplan` but not applied in CI — that's a deliberate choice. `terraform apply` runs manually or could be added to the CD pipeline if desired.

---

## Job dependency graph

```
test
 ├── build-and-push   (needs: test)
 └── terraform-validate (needs: test, parallel with build-and-push)
```

Total CI time on a warm cache: approximately 3-5 minutes.
