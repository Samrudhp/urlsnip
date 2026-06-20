import os
import random
import string
import boto3
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Shortener Service")

# Clients
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
)
sqs = boto3.client(
    "sqs",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
)
cache = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "urlsnip")
QUEUE_URL  = os.getenv("SQS_QUEUE_URL", "")

class ShortenRequest(BaseModel):
    url: str

def generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

@app.get("/health")
def health():
    return {"status": "ok", "service": "shortener"}

@app.post("/shorten")
def shorten(req: ShortenRequest):
    code = generate_code()
    table = dynamodb.Table(TABLE_NAME)

    # Store in DynamoDB
    table.put_item(Item={"code": code, "url": req.url, "clicks": 0})

    # Cache it in Redis
    cache.set(f"url:{code}", req.url, ex=3600)

    # Publish event to SQS
    if QUEUE_URL:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=f'{{"code": "{code}", "url": "{req.url}", "event": "created"}}',
        )

    return {"code": code, "short_url": f"http://localhost:8001/{code}"}

@app.get("/links")
def list_links():
    table = dynamodb.Table(TABLE_NAME)
    result = table.scan()
    return {"links": result.get("Items", [])}