import re

with open("scripts/ingest_yt_json.py", "r") as f:
    content = f.read()

new_logic = """    filename = os.path.basename(args.file_path)
    video_id = filename.split('_')[0]
    
    # Extract title from filename (removing id, date, language, extension)
    # Format: {id}_{channel_and_title}_{date}_{lang}.json
    title_part = filename[len(video_id)+1:]
    title_part = re.sub(r'_\\d{4}-\\d{2}-\\d{2}_[a-z]{2}\\.json$', '', title_part)
    title_part = title_part.replace('_', ' ')
    video_title = title_part or "YouTube Video"

    if len(video_id) != 11:"""

content = re.sub(
    r"    filename = os.path.basename\(args.file_path\).*?if len\(video_id\) != 11:",
    new_logic,
    content,
    flags=re.DOTALL,
)

new_submit = """        import hashlib
        hash_input = f"https://www.youtube.com/watch?v={video_id}"
        source_id = hashlib.md5(hash_input.encode()).hexdigest()[:12]
        
        resp = q.submit_job(
            source_id=source_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            source_type="youtube",
            s3_transcript_json_uri=http_uri,
            s3_audio_uri=None,
            track_id="yt_api"
        )"""

content = re.sub(
    r'        resp = q.submit_job\(.*?track_id="yt_api"\n        \)',
    new_submit,
    content,
    flags=re.DOTALL,
)

with open("scripts/ingest_yt_json.py", "w") as f:
    f.write(content)
