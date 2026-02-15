import os
import yt_dlp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_audio_for_videos(video_ids):
    output_dir = "data/audio"
    os.makedirs(output_dir, exist_ok=True)

    for video_id in video_ids:
        # Clean ID
        video_id = video_id.replace("\\u0026pp", "")
        url = f"https://www.youtube.com/watch?v={video_id}"

        logger.info(f"Processing video: {url}")

        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": os.path.join(output_dir, f"{video_id}.%(ext)s"),
            "quiet": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info(f"Successfully downloaded audio for {video_id}")
        except Exception as e:
            logger.error(f"Failed to download {video_id}: {e}")


if __name__ == "__main__":
    # IDs found from previous search
    video_ids = ["fTb9AvgReq8", "hn2PTMGLO2Q", "Jcc-L86qtjU"]
    download_audio_for_videos(video_ids)
