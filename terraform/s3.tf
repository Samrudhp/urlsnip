resource "aws_s3_bucket" "backups" {
  bucket = var.bucket_name

  tags = {
    Project = "urlsnip"
    Env     = "local"
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id

  versioning_configuration {
    status = "Enabled"
  }
}