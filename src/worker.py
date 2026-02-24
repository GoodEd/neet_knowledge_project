import json
import logging
import os
import time

import boto3
from dotenv import load_dotenv

from src.jobs.queue import IngestionQueue
from src.rag.neet_rag import NEETRAG
from src.utils.content_manager import AutoUpdater, ContentSourceManager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_job(body: str):
    data = json.loads(body)
    source = data.get("source") or data.get("url")
    source_type = data.get("source_type") or data.get("type") or "auto"
    source_id = data.get("source_id")
    s3_audio_uri = data.get("s3_audio_uri")
    s3_transcript_json_uri = data.get("s3_transcript_json_uri")
    track_id = data.get("track_id")
    return (
        source_id,
        source,
        source_type,
        s3_audio_uri,
        s3_transcript_json_uri,
        track_id,
    )


def main():
    load_dotenv()

    queue = IngestionQueue()
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    rag = NEETRAG(
        llm_provider="openai",
        llm_model=os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001"),
        llm_base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    source_manager = ContentSourceManager()
    updater = AutoUpdater(source_manager, rag)

    logger.info("Worker started. Polling queue: %s", queue.queue_url)

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=queue.queue_url,
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
                (
                    source_id,
                    source,
                    source_type,
                    s3_audio_uri,
                    s3_transcript_json_uri,
                    track_id,
                ) = _extract_job(body)
            except Exception:
                logger.exception("Invalid message body. Deleting message: %s", body)
                sqs.delete_message(QueueUrl=queue.queue_url, ReceiptHandle=receipt)
                continue

            if not source:
                logger.warning("Message missing source/url. Deleting message: %s", body)
                sqs.delete_message(QueueUrl=queue.queue_url, ReceiptHandle=receipt)
                continue

            logger.info(
                "Processing ingestion job: source_id=%s source=%s type=%s track_id=%s s3_audio_uri=%s s3_transcript_json_uri=%s",
                source_id,
                source,
                source_type,
                track_id,
                s3_audio_uri,
                s3_transcript_json_uri,
            )
            source_record = None
            if source_id:
                try:
                    source_record = source_manager.get_source(source_id)
                except Exception:
                    pass
            
            # If source doesn't exist in DB, create it automatically
            if source_id and not source_record:
                logger.info(f"Auto-registering missing source_id={source_id} in database")
                new_metadata = {}
                if s3_audio_uri:
                    new_metadata["s3_audio_uri"] = s3_audio_uri
                if s3_transcript_json_uri:
                    new_metadata["s3_transcript_json_uri"] = s3_transcript_json_uri
                if track_id:
                    new_metadata["track_id"] = track_id
                # if video_title:
                #     new_metadata["video_title"] = video_title
                    
                # We do a direct DB insertion so we don't accidentally re-hash the source_id
                from datetime import datetime
                import json
                try:
                    source_manager.conn.execute(
                        '''
                        INSERT OR IGNORE INTO sources (
                            source_id, url, source_type, title, last_fetched, last_updated,
                            fetch_interval_hours, status, error_message, metadata, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            source_id, source, source_type, video_title or source,
                            datetime.now().isoformat(), datetime.now().isoformat(),
                            24, 'active', None, json.dumps(new_metadata) if new_metadata else None,
                            datetime.now().isoformat(), datetime.now().isoformat()
                        )
                    )
                    source_manager.conn.commit()
                    source_record = source_manager.get_source(source_id)
                except Exception as e:
                    logger.error(f"Failed to auto-register source: {e}")

            if source_id and source_record:
                if s3_audio_uri or s3_transcript_json_uri or track_id:
                    src = source_record
                    if src:
                        new_metadata = src.metadata or {}
                        if s3_audio_uri:
                            new_metadata["s3_audio_uri"] = s3_audio_uri
                        if s3_transcript_json_uri:
                            new_metadata["s3_transcript_json_uri"] = (
                                s3_transcript_json_uri
                            )
                        if track_id:
                            new_metadata["track_id"] = track_id
                        source_manager.set_source_metadata(source_id, new_metadata)
                update_result = updater.update_source(source_id)
                failed = update_result.get("status") != "success"
                result = update_result
            else:
                if source_type == "youtube" and (
                    s3_audio_uri or s3_transcript_json_uri or track_id
                ):
                    processed = rag.content_processor.process_youtube(
                        source,
                        s3_audio_uri=s3_audio_uri,
                        s3_transcript_json_uri=s3_transcript_json_uri,
                        track_id=track_id,
                    )
                    result = rag.ingest_processed_content(processed)
                    failed = result.get("status") != "success"
                else:
                    result = rag.ingest_content(source, source_type=source_type)
                    failed = result.get("total_failed", 0)

            if failed:
                logger.error("Ingestion failed for %s: %s", source, result)
                sqs.delete_message(QueueUrl=queue.queue_url, ReceiptHandle=receipt)
                continue

            sqs.delete_message(QueueUrl=queue.queue_url, ReceiptHandle=receipt)
            logger.info("Ingestion succeeded and message deleted: %s", source)

        except Exception:
            logger.exception("Worker loop error; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
