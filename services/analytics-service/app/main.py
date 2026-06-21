import os
import json
import threading
import boto3
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Analytics Service")

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

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

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "urlsnip")
QUEUE_URL  = os.getenv("SQS_QUEUE_URL", "")

def poll_sqs():
    """Background thread: consume SQS events and update click counts."""
    while True:
        if not QUEUE_URL:
            continue
        try:
            resp = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5,
            )
            for msg in resp.get("Messages", []):
                body = json.loads(msg["Body"])
                code = body.get("code")
                if code:
                    table = dynamodb.Table(TABLE_NAME)
                    table.update_item(
                        Key={"code": code},
                        UpdateExpression="ADD clicks :inc",
                        ExpressionAttributeValues={":inc": 1},
                    )
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
        except Exception as e:
            print(f"SQS poll error: {e}")

@app.on_event("startup")
def startup():
    t = threading.Thread(target=poll_sqs, daemon=True)
    t.start()

@app.get("/health")
def health():
    return {"status": "ok", "service": "analytics"}

@app.get("/stats/{code}")
def stats(code: str):
    table = dynamodb.Table(TABLE_NAME)
    result = table.get_item(Key={"code": code})
    item = result.get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="Code not found")
    return {"code": code, "url": item["url"], "clicks": int(item.get("clicks", 0))}

@app.get("/stats")
def all_stats():
    table = dynamodb.Table(TABLE_NAME)
    result = table.scan()
    return {"stats": result.get("Items", [])}