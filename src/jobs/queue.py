import json
import os

import boto3


class IngestionQueue:
    def __init__(self, queue_url: str | None = None, region_name: str | None = None):
        self.queue_url = queue_url or os.getenv("SQS_QUEUE_URL")
        self.region_name = region_name or os.getenv("AWS_REGION")
        if not self.queue_url:
            raise ValueError("SQS_QUEUE_URL is required")
        self.sqs = boto3.client("sqs", region_name=self.region_name)

    def submit_job(self, source_id: str, url: str, source_type: str):
        body = {
            "source_id": source_id,
            "url": url,
            "source_type": source_type,
        }
        return self.sqs.send_message(
            QueueUrl=self.queue_url, MessageBody=json.dumps(body)
        )
