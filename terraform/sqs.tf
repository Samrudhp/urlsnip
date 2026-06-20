resource "aws_sqs_queue" "urlsnip_events" {
  name                      = var.queue_name
  message_retention_seconds = 86400
  visibility_timeout_seconds = 30

  tags = {
    Project = "urlsnip"
    Env     = "local"
  }
}