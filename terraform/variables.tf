variable "aws_endpoint" {
  default = "http://localhost:4566"
}

variable "aws_region" {
  default = "us-east-1"
}

variable "table_name" {
  default = "urlsnip"
}

variable "queue_name" {
  default = "urlsnip-events"
}

variable "bucket_name" {
  default = "urlsnip-backups"
}