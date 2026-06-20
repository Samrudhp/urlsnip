import os
import boto3
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

app = FastAPI(title="Redirect Service")

dynamodb = boto3.resource(
    "dynamodb",
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

@app.get("/health")
def health():
    return {"status": "ok", "service": "redirect"}

@app.get("/{code}")
def redirect(code: str):
    # Check Redis cache first
    cached = cache.get(f"url:{code}")
    if cached:
        return RedirectResponse(url=cached, status_code=302)

    # Fall back to DynamoDB
    table = dynamodb.Table(TABLE_NAME)
    result = table.get_item(Key={"code": code})
    item = result.get("Item")

    if not item:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Warm the cache
    cache.set(f"url:{code}", item["url"], ex=3600)

    return RedirectResponse(url=item["url"], status_code=302)