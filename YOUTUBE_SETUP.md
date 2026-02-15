
## Getting a YouTube Data API Key

To use the official YouTube integration for metadata, you need a Google Cloud API Key.

1.  **Go to Google Cloud Console**:
    Visit [https://console.cloud.google.com/](https://console.cloud.google.com/) and sign in.

2.  **Create a Project**:
    *   Click the project dropdown in the top bar.
    *   Click **"New Project"**.
    *   Name it (e.g., "NEET Knowledge") and create it.

3.  **Enable YouTube Data API v3**:
    *   In the sidebar, go to **"APIs & Services" > "Library"**.
    *   Search for **"YouTube Data API v3"**.
    *   Click on it and select **"Enable"**.

4.  **Create Credentials**:
    *   Go to **"APIs & Services" > "Credentials"**.
    *   Click **"Create Credentials"** (top of screen) and select **"API Key"**.
    *   Your new API key will appear. **Copy this key**.

5.  **Configure Environment**:
    *   Open your `.env` file in the project root.
    *   Add the line:
        ```bash
        YOUTUBE_API_KEY=your_copied_api_key_here
        ```

### Note on Transcripts
The official YouTube Data API does **not** allow downloading transcripts (captions) for public videos easily without OAuth. This system uses a hybrid approach:
- **Official API**: Used for reliable metadata (Title, Duration, Channel).
- **yt-dlp**: Used to fetch the actual transcript text (with fallbacks).
