import json
import logging
import os
import time

import boto3
from dotenv import load_dotenv

from src.rag.neet_rag import NEETRAG


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_job(body: str):
    data = json.loads(body)
    source = data.get("source") or data.get("url")
    source_type = data.get("source_type") or data.get("type") or "auto"
    return source, source_type


def main():
    load_dotenv()

    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("SQS_QUEUE_URL is required for worker")

    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    rag = NEETRAG(
        llm_provider="openai",
        llm_model=os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001"),
        llm_base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )

    logger.info("Worker started. Polling queue: %s", queue_url)

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=300,
            )
            messages = resp.get("Messages", [])
            if not messages:
                continue

            msg = messages[0]
            receipt = msg["ReceiptHandle"]
            body = msg.get("Body", "{}")

            try:
                source, source_type = _extract_job(body)
            except Exception:
                logger.exception("Invalid message body. Deleting message: %s", body)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                continue

            if not source:
                logger.warning("Message missing source/url. Deleting message: %s", body)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                continue

            logger.info(
                "Processing ingestion job: source=%s type=%s", source, source_type
            )
            result = rag.ingest_content(source, source_type=source_type)
            failed = result.get("total_failed", 0)
            if failed:
                logger.error("Ingestion failed for %s: %s", source, result)
                continue

            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
            logger.info("Ingestion succeeded and message deleted: %s", source)

        except Exception:
            logger.exception("Worker loop error; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
