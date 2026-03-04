import re

with open("src/worker.py", "r") as f:
    content = f.read()

new_logic = """            source_record = None
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
                            source_id, source, source_type, source,
                            datetime.now().isoformat(), datetime.now().isoformat(),
                            24, 'active', None, json.dumps(new_metadata) if new_metadata else None,
                            datetime.now().isoformat(), datetime.now().isoformat()
                        )
                    )
                    source_manager.conn.commit()
                    source_record = source_manager.get_source(source_id)
                except Exception as e:
                    logger.error(f"Failed to auto-register source: {e}")

            if source_id and source_record:"""

content = re.sub(
    r"            source_record = None.*?if source_id and source_record:",
    new_logic,
    content,
    flags=re.DOTALL,
)

with open("src/worker.py", "w") as f:
    f.write(content)
