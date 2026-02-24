import argparse
import os
import sys
import boto3
import uuid
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.jobs.queue import IngestionQueue

def main():
    parser = argparse.ArgumentParser(description="Upload CSV to S3 and queue ingestion")
    parser.add_argument("file_path", help="Path to the local CSV file")
    parser.add_argument("--bucket", default="neetprep-static-assets", help="S3 bucket name")
    parser.add_argument("--folder", default="csv_assets", help="S3 folder path")
    args = parser.parse_args()

    if not os.path.exists(args.file_path):
        print(f"Error: File not found: {args.file_path}")
        sys.exit(1)

    filename = os.path.basename(args.file_path)
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

    print(f"Queueing CSV ingestion...")
    
    try:
        q = IngestionQueue(queue_url="https://sqs.ap-south-1.amazonaws.com/559387212220/neet-knowledge-dev-ingestion")
        resp = q.submit_job(
            source_id=str(uuid.uuid4())[:12],
            url=http_uri,
            source_type="csv"
        )
        print("Successfully queued job!")
        print(f"S3 URI: {s3_uri}")
        print(f"HTTP URI: {http_uri}")
        print(f"Message ID: {resp.get('MessageId')}")
    except Exception as e:
        print(f"Failed to submit to SQS. Error: {e}")

if __name__ == "__main__":
    main()
