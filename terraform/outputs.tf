output "dynamodb_table_name" {
  value = aws_dynamodb_table.urlsnip.name
}

output "dynamodb_table_arn" {
  value = aws_dynamodb_table.urlsnip.arn
}

output "sqs_queue_url" {
  value = aws_sqs_queue.urlsnip_events.url
}

output "sqs_queue_arn" {
  value = aws_sqs_queue.urlsnip_events.arn
}

output "s3_bucket_name" {
  value = aws_s3_bucket.backups.bucket
}