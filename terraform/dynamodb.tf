resource "aws_dynamodb_table" "urlsnip" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "code"

  attribute {
    name = "code"
    type = "S"
  }

  tags = {
    Project = "urlsnip"
    Env     = "local"
  }
}