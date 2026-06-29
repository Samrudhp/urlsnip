# Terraform

Terraform manages the three AWS resources that urlsnip needs: the DynamoDB table, the SQS queue, and the S3 bucket. All resources are provisioned against Floci at `http://localhost:4566`.

## What Terraform manages

| Resource | Terraform ID | AWS Resource |
|---|---|---|
| DynamoDB table | `aws_dynamodb_table.urlsnip` | `urlsnip` |
| SQS queue | `aws_sqs_queue.urlsnip_events` | `urlsnip-events` |
| S3 bucket | `aws_s3_bucket.backups` | `urlsnip-backups` |
| S3 versioning | `aws_s3_bucket_versioning.backups` | enabled on `urlsnip-backups` |

## File breakdown

### `main.tf`

Configures the AWS provider to skip all the real-AWS validation that would fail against Floci:

```hcl
provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    dynamodb = var.aws_endpoint
    sqs      = var.aws_endpoint
    s3       = var.aws_endpoint
  }

  s3_use_path_style = true
}
```

`s3_use_path_style = true` is required for Floci — the default virtual-hosted style (`bucket.localhost`) doesn't work locally.

### `variables.tf`

| Variable | Default | Used for |
|---|---|---|
| `aws_endpoint` | `http://localhost:4566` | All AWS service endpoints |
| `aws_region` | `us-east-1` | Provider region |
| `table_name` | `urlsnip` | DynamoDB table name |
| `queue_name` | `urlsnip-events` | SQS queue name |
| `bucket_name` | `urlsnip-backups` | S3 bucket name |

### `dynamodb.tf`

Creates the `urlsnip` table with `code` (String) as the hash key, `PAY_PER_REQUEST` billing mode (no capacity to manage), and `Project=urlsnip` / `Env=local` tags.

### `sqs.tf`

Creates the `urlsnip-events` queue with:
- `message_retention_seconds = 86400` — messages kept for 24 hours
- `visibility_timeout_seconds = 30` — messages invisible for 30s after a consumer picks them up (gives the analytics service time to process and delete before the message reappears)

### `s3.tf`

Creates the `urlsnip-backups` bucket and enables versioning on it. Versioning means every overwritten or deleted object is retained as a previous version.

### `outputs.tf`

After apply, Terraform prints:
- `dynamodb_table_name` and `dynamodb_table_arn`
- `sqs_queue_url` and `sqs_queue_arn`
- `s3_bucket_name`

## Running Terraform

```bash
cd terraform/

# Set env vars (Floci credentials)
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1

# Initialize (downloads the AWS provider ~500MB first time)
terraform init

# See what will be created
terraform plan

# Create all resources
terraform apply
# Type "yes" when prompted

# Check outputs
terraform output
# dynamodb_table_name = "urlsnip"
# sqs_queue_url = "http://localhost:4566/000000000000/urlsnip-events"
# s3_bucket_name = "urlsnip-backups"

# Destroy all resources
terraform destroy
# Type "yes" when prompted
```

## State management

The state file is `terraform/terraform.tfstate`. It lives locally in the repo (`.gitignore` should exclude it in a real project, but it's kept here since state contains no secrets — only Floci resource IDs).

`terraform.tfstate.backup` is automatically written before each apply as a safety snapshot.

To inspect current state:

```bash
# List all managed resources
terraform state list

# Show details of a resource
terraform state show aws_dynamodb_table.urlsnip

# Refresh state from Floci (re-read actual resource state)
terraform refresh
```

## Pointing at a different endpoint

To run Terraform against a different Floci instance or port:

```bash
terraform plan -var="aws_endpoint=http://localhost:4566"
terraform apply -var="aws_endpoint=http://localhost:4566"
```

The CI pipeline uses `terraform plan -var="aws_endpoint=http://localhost:4566"` explicitly even though it's the default, to make the intent clear.

## Relationship to Docker Compose

Docker Compose's `floci-init` service creates the same DynamoDB table and SQS queue using AWS CLI commands. Terraform is an alternative (and the IaC-preferred) way to create the same resources. In the Kubernetes workflow, you run Terraform to set up Floci resources instead of relying on the Docker Compose init container.

Running both Docker Compose and Terraform against the same Floci instance will create duplicate resources. If the Docker Compose stack is running when you run `terraform apply`, Terraform may fail with a resource-already-exists error. Either:
- Run `docker compose down` before `terraform apply`, or
- Import existing resources: `terraform import aws_dynamodb_table.urlsnip urlsnip`
