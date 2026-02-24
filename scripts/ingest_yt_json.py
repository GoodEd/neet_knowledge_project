import argparse
import os
import sys
import boto3
import uuid
import json

# Add parent dir to path to import queue logic
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.jobs.queue import IngestionQueue

def main():
    parser = argparse.ArgumentParser(description="Upload YouTube transcript JSON to S3 and queue ingestion")
    parser.add_argument("file_path", help="Path to the local JSON file")
    parser.add_argument("--bucket", default="neetprep-static-assets", help="S3 bucket name")
    parser.add_argument("--folder", default="yt_pyq_assets", help="S3 folder path")
    args = parser.parse_args()

    if not os.path.exists(args.file_path):
        print(f"Error: File not found: {args.file_path}")
        sys.exit(1)

    filename = os.path.basename(args.file_path)
    video_id = filename.split('_')[0]

    if len(video_id) != 11:
        print(f"Warning: Extracted video ID '{video_id}' is not 11 characters long. Are you sure the filename is correct?")

    s3_key = f"{args.folder.rstrip('/')}/{filename}"
    s3_uri = f"s3://{args.bucket}/{s3_key}"
    http_uri = f"https://{args.bucket}.s3.{boto3.session.Session().region_name or 'ap-south-1'}.amazonaws.com/{s3_key}"

    print(f"Uploading {args.file_path} to {s3_uri}...")
    s3_client = boto3.client('s3')
    
    try:
        s3_client.upload_file(args.file_path, args.bucket, s3_key)
        print("Upload successful!")
    except Exception as e:
        print(f"Failed to upload to S3: {e}")
        sys.exit(1)

    print(f"Queueing ingestion for video: {video_id}")
    
    try:
        q = IngestionQueue(queue_url="https://sqs.ap-south-1.amazonaws.com/559387212220/neet-knowledge-dev-ingestion")
        # We pass s3_audio_uri=None intentionally here
        resp = q.submit_job(
            source_id=str(uuid.uuid4())[:12],
            url=f"https://www.youtube.com/watch?v={video_id}",
            source_type="youtube",
            s3_transcript_json_uri=http_uri,
            s3_audio_uri=None,
            track_id="yt_api"
        )
        print("Successfully queued job!")
        print(f"S3 URI: {s3_uri}")
        print(f"HTTP URI: {http_uri}")
        print(f"Message ID: {resp.get('MessageId')}")
    except Exception as e:
        print(f"Failed to submit to SQS. Error: {e}")

if __name__ == "__main__":
    main()
