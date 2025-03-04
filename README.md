# Vimeo Downloader

A command line application to connect to Vimeo using OAuth2, list all videos, and download them.

## Setup

1. Register a new app on Vimeo:
   - Go to https://developer.vimeo.com/apps
   - Click "Create App"
   - Fill in the required information (name, description, etc.)
   - For "App URL", you can use any valid URL (e.g., your GitHub profile)
   - Under "App Callback URLs", add EXACTLY `http://localhost:8080/callback` (make sure there are no trailing slashes or extra characters)
   - Click "Create" to create the app

2. Configure app permissions:
   - In your app settings, go to the "Authentication" tab
   - Under "Permissions", make sure the following scopes are enabled:
     - Private: View private videos, interact with private videos, etc.
     - Video Files: View and download video files
   - Save your changes
   - Note your Client ID and Client Secret from the "Authentication" tab

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root with your Vimeo API credentials:
   ```
   VIMEO_CLIENT_ID=your_client_id
   VIMEO_CLIENT_SECRET=your_client_secret
   ```

## Usage

1. Run the authentication setup (first time only):
   ```
   python vimeo_downloader.py auth
   ```
   This will open a browser window for you to authorize the application.

2. List all your videos:
   ```
   python vimeo_downloader.py list
   ```

3. Download all videos:
   ```
   python vimeo_downloader.py download
   ```

4. Download a specific video by ID:
   ```
   python vimeo_downloader.py download --video-id VIDEO_ID
   ```

5. Download with additional options:
   ```
   # Limit to downloading only the first 3 videos
   python vimeo_downloader.py download --count 3
   
   # Enable debug mode to see full JSON responses
   python vimeo_downloader.py download --debug
   
   # Combine options
   python vimeo_downloader.py download --video-id VIDEO_ID --debug
   ```

6. Show help:
   ```
   python vimeo_downloader.py --help
   ```

## Download Permissions

To download videos from Vimeo, you need to have the appropriate permissions:

1. You must be the owner of the videos or have download permission granted by the owner.
2. The video owner must have enabled downloads for the videos.
3. Your Vimeo account must have the necessary privileges to download videos (some features may be limited to Vimeo Pro, Business, or Premium accounts).

If you encounter issues with downloading videos, the application will provide detailed information about why the download might be failing.

## Troubleshooting

If you're having trouble downloading videos:

1. Make sure your Vimeo app has the "Video Files" scope enabled in the app settings.
2. Verify that you have permission to download the videos you're trying to access.
3. Check if the videos have download enabled by the owner.
4. For private videos, ensure your app has the "Private" scope enabled.
5. Some videos may be still processing on Vimeo's servers and not yet available for download.
