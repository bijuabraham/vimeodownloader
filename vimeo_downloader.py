#!/usr/bin/env python3
"""
Vimeo Downloader - A command line application to connect to Vimeo using OAuth2,
list all videos, and download them.
"""

import os
import sys
import json
import webbrowser
import http.server
import socketserver
import urllib.parse
from pathlib import Path
from datetime import datetime
import threading
import time

import click
import requests
import vimeo
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants
TOKEN_FILE = Path("vimeo_token.json")
DOWNLOAD_DIR = Path("downloads")
CALLBACK_PORT = 8080
CALLBACK_PATH = "/callback"
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

# Global variables
client_id = os.getenv("VIMEO_CLIENT_ID")
client_secret = os.getenv("VIMEO_CLIENT_SECRET")
access_token = None
vimeo_client = None


class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
    """Handler for OAuth callback."""
    
    def do_GET(self):
        """Handle GET request to callback URL."""
        if self.path.startswith(CALLBACK_PATH):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            
            # Parse the query parameters
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            
            if "code" in params:
                # Write the authorization code to the response
                response = f"""
                <html>
                <head><title>Authorization Successful</title></head>
                <body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the command line.</p>
                <script>
                    // Store the code in localStorage so the main thread can access it
                    localStorage.setItem('vimeo_auth_code', '{params["code"][0]}');
                </script>
                </body>
                </html>
                """
                self.wfile.write(response.encode())
                
                # Store the code in a class variable so the main thread can access it
                OAuthCallbackHandler.auth_code = params["code"][0]
            else:
                # Handle error
                error = params.get("error", ["Unknown error"])[0]
                response = f"""
                <html>
                <head><title>Authorization Failed</title></head>
                <body>
                <h1>Authorization Failed</h1>
                <p>Error: {error}</p>
                </body>
                </html>
                """
                self.wfile.write(response.encode())
                OAuthCallbackHandler.auth_code = None
                
            # Signal that we've received the callback
            OAuthCallbackHandler.callback_received = True
            
            return
            
        return super().do_GET()


def get_vimeo_client():
    """Get an authenticated Vimeo client."""
    global vimeo_client, access_token
    
    # Check if we already have a client
    if vimeo_client:
        return vimeo_client
    
    # Check if we have a token file
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)
            access_token = token_data.get("access_token")
            
        if access_token:
            vimeo_client = vimeo.VimeoClient(
                token=access_token,
                key=client_id,
                secret=client_secret
            )
            return vimeo_client
    
    click.echo("No valid authentication token found. Please run 'auth' command first.")
    sys.exit(1)


def authenticate():
    """Authenticate with Vimeo using OAuth2."""
    global vimeo_client, access_token
    
    if not client_id or not client_secret:
        click.echo("Error: VIMEO_CLIENT_ID and VIMEO_CLIENT_SECRET must be set in .env file")
        click.echo("Please follow the setup instructions in the README.md")
        sys.exit(1)
    
    # Initialize the Vimeo client for authentication
    v = vimeo.VimeoClient(
        key=client_id,
        secret=client_secret
    )
    
    # Get the authorization URL
    auth_url = v.auth_url(
        ["private", "video_files"],
        CALLBACK_URL,
        "code"
    )
    
    click.echo("Opening browser for Vimeo authentication...")
    click.echo(f"If the browser doesn't open automatically, visit: {auth_url}")
    
    # Open the browser for authentication
    webbrowser.open(auth_url)
    
    # Start a local server to receive the callback
    OAuthCallbackHandler.callback_received = False
    OAuthCallbackHandler.auth_code = None
    
    # Create a server that will shut down after receiving the callback
    httpd = socketserver.TCPServer(("", CALLBACK_PORT), OAuthCallbackHandler)
    
    # Run the server in a separate thread so we can have a timeout
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    # Wait for the callback or timeout
    timeout = 300  # 5 minutes
    start_time = time.time()
    
    click.echo("Waiting for authentication (timeout in 5 minutes)...")
    
    while not OAuthCallbackHandler.callback_received:
        if time.time() - start_time > timeout:
            click.echo("Authentication timed out. Please try again.")
            httpd.shutdown()
            sys.exit(1)
        time.sleep(1)
    
    # Shutdown the server
    httpd.shutdown()
    
    if not OAuthCallbackHandler.auth_code:
        click.echo("Authentication failed. No authorization code received.")
        sys.exit(1)
    
    # Exchange the authorization code for an access token
    try:
        # The exchange_code method returns a tuple with (access_token, None, scope)
        token_response = v.exchange_code(OAuthCallbackHandler.auth_code, CALLBACK_URL)
        
        # Extract the access token from the tuple
        access_token = token_response[0]
        
        if not access_token:
            click.echo("Failed to get access token.")
            sys.exit(1)
        
        # Create a token data dictionary to save
        token_data = {
            "access_token": access_token,
            "scope": token_response[2] if len(token_response) > 2 else "",
            "created_at": datetime.now().isoformat()
        }
        
        # Save the token to a file
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f)
        
        click.echo("Authentication successful! Token saved.")
        
        # Initialize the client with the new token
        vimeo_client = vimeo.VimeoClient(
            token=access_token,
            key=client_id,
            secret=client_secret
        )
        
        return vimeo_client
        
    except Exception as e:
        click.echo(f"Error exchanging authorization code for access token: {e}")
        sys.exit(1)


def list_videos(limit=None):
    """List all videos in the user's account."""
    client = get_vimeo_client()
    
    try:
        # Get the first page of videos
        response = client.get("/me/videos", params={"per_page": 100})
        
        if response.status_code != 200:
            click.echo(f"Error fetching videos: {response.text}")
            sys.exit(1)
        
        videos = response.json()["data"]
        total_videos = len(videos)
        
        # If there are more pages, fetch them
        next_page = response.json().get("paging", {}).get("next")
        while next_page and (limit is None or total_videos < limit):
            response = client.get(next_page)
            if response.status_code != 200:
                break
                
            page_videos = response.json()["data"]
            videos.extend(page_videos)
            total_videos = len(videos)
            
            next_page = response.json().get("paging", {}).get("next")
            
            if limit and total_videos >= limit:
                videos = videos[:limit]
                break
        
        if not videos:
            click.echo("No videos found in your account.")
            return []
        
        # Display the videos
        click.echo(f"Found {len(videos)} videos:")
        for i, video in enumerate(videos, 1):
            created_time = datetime.fromisoformat(video["created_time"].replace("Z", "+00:00"))
            formatted_time = created_time.strftime("%Y-%m-%d %H:%M:%S")
            
            click.echo(f"{i}. [{video['uri'].split('/')[-1]}] {video['name']} "
                       f"({video['duration']} seconds, {formatted_time})")
        
        return videos
        
    except Exception as e:
        click.echo(f"Error listing videos: {e}")
        sys.exit(1)


def find_best_resolution(links, prefer_hd=True):
    """Find the best resolution download link.
    
    Args:
        links: List of download links
        prefer_hd: If True, prefer 720p resolution; if False, get highest resolution
        
    Returns:
        The best download link based on the preference
    """
    if not links:
        return None
        
    # If we want the highest resolution, just sort and return the first
    if not prefer_hd:
        links.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
        return links[0]
        
    # Find the link closest to 720p
    target_height = 720
    closest_link = None
    min_diff = float('inf')
    
    for link in links:
        height = link.get("height", 0)
        if height > 0:
            diff = abs(height - target_height)
            if diff < min_diff:
                min_diff = diff
                closest_link = link
    
    # If we couldn't find a good match, fall back to highest resolution
    if not closest_link:
        links.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
        return links[0]
        
    return closest_link


def get_best_download_link(video, client, debug=False, prefer_hd=True):
    """Get the best quality download link for a video.
    
    Args:
        video: The video object from the Vimeo API
        client: The Vimeo client
        debug: Whether to print debug information
        prefer_hd: If True, prefer 720p resolution; if False, get highest resolution
    """
    video_id = video["uri"].split("/")[-1]
    video_name = video["name"]
    
    # Print the full video JSON if debug is enabled
    if debug:
        click.echo("\n=== VIDEO JSON ===")
        click.echo(json.dumps(video, indent=2))
        click.echo("=== END VIDEO JSON ===\n")
    
    # First, check if download links are directly available in the video object
    download_links = video.get("download", [])
    
    if download_links:
        click.echo(f"Found {len(download_links)} direct download links for {video_name}")
        if debug:
            click.echo("\n=== DOWNLOAD LINKS ===")
            click.echo(json.dumps(download_links, indent=2))
            click.echo("=== END DOWNLOAD LINKS ===\n")
        
        return find_best_resolution(download_links, prefer_hd)
    
    # Function to recursively search for direct links in the JSON
    def find_direct_links(obj, links=None):
        try:
            if links is None:
                links = []
            
            # Handle dictionary objects
            if isinstance(obj, dict):
                # Check if this dict has width, height, and link keys
                if all(k in obj for k in ["width", "height", "link"]):
                    width = obj.get("width", 0)
                    height = obj.get("height", 0)
                    link = obj.get("link", "")
                    
                    # Check if it's a valid link with dimensions
                    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
                        if isinstance(link, str) and ("vimeocdn.com" in link or "vimeo.com" in link):
                            links.append({
                                "quality": "hd",
                                "type": "video/mp4",
                                "width": width,
                                "height": height,
                                "link": link,
                                "size": 0
                            })
                
                # Recursively search in all dict values
                for key, value in obj.items():
                    find_direct_links(value, links)
            
            # Handle list objects
            elif isinstance(obj, list):
                # Recursively search in all list items
                for item in obj:
                    find_direct_links(item, links)
            
            return links
        except Exception as e:
            click.echo(f"Error in find_direct_links: {e}")
            return links
    
    # Check specifically for thumbnail links in the pictures field
    if "pictures" in video and isinstance(video["pictures"], dict) and "sizes" in video["pictures"]:
        picture_sizes = video["pictures"]["sizes"]
        if isinstance(picture_sizes, list) and len(picture_sizes) > 0:
            click.echo(f"Found {len(picture_sizes)} picture sizes with potential direct links")
            
            # Sort by resolution (highest first)
            picture_sizes.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            
            # Find links that might be video links
            thumbnail_links = []
            for size in picture_sizes:
                if "link" in size and size.get("width", 0) > 0 and size.get("height", 0) > 0:
                    # Try to convert thumbnail link to video link
                    link = size["link"]
                    if isinstance(link, str) and "vimeocdn.com" in link:
                        # This is a thumbnail link, try to modify it to be a video link
                        # Example: https://i.vimeocdn.com/video/1916303757-26de291879744055a47434bb1663d63fbd044aaeaf86a63357a4712f2bee51dd-d_1280x720
                        
                        # Try to extract the video ID from the thumbnail URL
                        try:
                            # Extract the part after /video/ and before the next dash or underscore
                            parts = link.split("/video/")[1].split("-")[0]
                            if parts:
                                # Try to construct a video download link
                                # First, try the original thumbnail link
                                thumbnail_links.append({
                                    "quality": "hd",
                                    "type": "video/mp4",
                                    "width": size.get("width", 0),
                                    "height": size.get("height", 0),
                                    "link": link,
                                    "size": 0
                                })
                                
                                # Then try a modified version that might be a video link
                                # Replace i.vimeocdn.com with player.vimeo.com and add /video.mp4
                                video_link = link.replace("i.vimeocdn.com/video", "player.vimeo.com/video")
                                if "_" in video_link:
                                    video_link = video_link.split("_")[0] + "/video.mp4"
                                else:
                                    video_link = video_link + "/video.mp4"
                                
                                thumbnail_links.append({
                                    "quality": "hd",
                                    "type": "video/mp4",
                                    "width": size.get("width", 0),
                                    "height": size.get("height", 0),
                                    "link": video_link,
                                    "size": 0
                                })
                        except Exception as e:
                            click.echo(f"Error converting thumbnail link: {e}")
                            # Still add the original thumbnail link
                            thumbnail_links.append({
                                "quality": "hd",
                                "type": "video/mp4",
                                "width": size.get("width", 0),
                                "height": size.get("height", 0),
                                "link": link,
                                "size": 0
                            })
            
            if thumbnail_links and debug:
                click.echo("\n=== THUMBNAIL LINKS ===")
                click.echo(json.dumps(thumbnail_links, indent=2))
                click.echo("=== END THUMBNAIL LINKS ===\n")
                
            # Add thumbnail links to direct links for consideration
            direct_links = thumbnail_links + find_direct_links(video)
        else:
            direct_links = find_direct_links(video)
    else:
        direct_links = find_direct_links(video)
    
    if direct_links:
        click.echo(f"Found {len(direct_links)} direct links in the video JSON")
        
        if debug:
            click.echo("\n=== DIRECT LINKS ===")
            click.echo(json.dumps(direct_links, indent=2))
            click.echo("=== END DIRECT LINKS ===\n")
        
        return find_best_resolution(direct_links, prefer_hd)
    
    # Try to get download links directly from the video's download endpoint
    click.echo(f"Trying to get download links directly from the download endpoint...")
    
    try:
        # Make a direct request to the video's download endpoint
        response = client.get(f"/videos/{video_id}/download")
        
        if response.status_code == 200:
            download_data = response.json()
            if isinstance(download_data, list) and len(download_data) > 0:
                click.echo(f"Found {len(download_data)} download links from download endpoint")
                return find_best_resolution(download_data, prefer_hd)
            else:
                click.echo("No download links found from download endpoint")
        else:
            click.echo(f"Error accessing download endpoint: {response.status_code}")
    except Exception as e:
        click.echo(f"Error accessing download endpoint: {e}")
    
    # If no direct download links, try to fetch the video with download field explicitly
    click.echo(f"No direct download links found for {video_name}. Trying to fetch download links explicitly...")
    
    try:
        # Make a specific request to get the video with download links
        response = client.get(f"/videos/{video_id}", params={"fields": "download"})
        
        if response.status_code != 200:
            click.echo(f"Error fetching video download links: {response.text}")
        else:
            video_data = response.json()
            download_links = video_data.get("download", [])
            
            if download_links and len(download_links) > 0:
                click.echo(f"Found {len(download_links)} download links from explicit request")
                return find_best_resolution(download_links, prefer_hd)
            else:
                click.echo("No download links found from explicit request")
    except Exception as e:
        click.echo(f"Error fetching explicit download links: {e}")
    
    # If still no download links, try to fetch the video with files field
    click.echo(f"Trying to fetch video files...")
    
    try:
        # Make a specific request to get the video with download links
        response = client.get(f"/videos/{video_id}", params={"fields": "files"})
        
        if response.status_code != 200:
            click.echo(f"Error fetching video files: {response.text}")
            return None
        
        video_data = response.json()
        
        # Check if we have files in the response
        files = video_data.get("files", [])
        
        if not files:
            click.echo(f"No files found for {video_name}")
            return None
        
        click.echo(f"Found {len(files)} files for {video_name}")
        
        # Debug the structure of the files
        click.echo(f"Files structure: {type(files)}")
        if files and len(files) > 0:
            click.echo(f"First file structure: {type(files[0])}")
        
        # Sort by quality (highest first)
        # Make sure we're handling the files correctly based on their structure
        try:
            if isinstance(files[0], dict):
                # If files is a list of dictionaries
                file_links = []
                for file in files:
                    file_links.append({
                        "quality": file.get("quality", "unknown"),
                        "type": file.get("type", "video/mp4"),
                        "width": file.get("width", 0),
                        "height": file.get("height", 0),
                        "link": file.get("link", None),
                        "size": file.get("size", 0)
                    })
                
                best_file = find_best_resolution(file_links, prefer_hd)
                if best_file:
                    return best_file
                
                # Fallback to old method if find_best_resolution fails
                files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                best_file = files[0]
                download_link = {
                    "quality": best_file.get("quality", "unknown"),
                    "type": best_file.get("type", "video/mp4"),
                    "width": best_file.get("width", 0),
                    "height": best_file.get("height", 0),
                    "link": best_file.get("link", None),
                    "size": best_file.get("size", 0)
                }
                return download_link
            else:
                # If files has a different structure, try to extract the download link
                click.echo(f"Files has an unexpected structure. Attempting to extract download link...")
                # Try to find a progressive download link
                progressive_files = [f for f in files if isinstance(f, dict) and f.get("quality") == "hd"]
                if progressive_files:
                    file_links = []
                    for file in progressive_files:
                        file_links.append({
                            "quality": file.get("quality", "unknown"),
                            "type": file.get("type", "video/mp4"),
                            "width": file.get("width", 0),
                            "height": file.get("height", 0),
                            "link": file.get("link", None),
                            "size": file.get("size", 0)
                        })
                    
                    best_file = find_best_resolution(file_links, prefer_hd)
                    if best_file:
                        return best_file
                    
                    # Fallback
                    best_file = progressive_files[0]
                    download_link = {
                        "quality": best_file.get("quality", "unknown"),
                        "type": best_file.get("type", "video/mp4"),
                        "width": best_file.get("width", 0),
                        "height": best_file.get("height", 0),
                        "link": best_file.get("link", None),
                        "size": best_file.get("size", 0)
                    }
                    return download_link
                else:
                    click.echo(f"Could not find a suitable download link in the files structure")
                    return None
        except Exception as e:
            click.echo(f"Error processing files: {e}")
            click.echo(f"Files content: {files}")
            return None
        
        if not download_link["link"]:
            click.echo(f"No download link found in files for {video_name}")
            return None
        
        return download_link
        
    except Exception as e:
        click.echo(f"Error getting download link for {video_name}: {e}")
        return None


def download_video(video_id=None, count=None, debug=False, prefer_hd=True, skip_ids=None):
    """Download videos from the user's account.
    
    Args:
        video_id: Optional ID of a specific video to download
        count: Optional limit on the number of videos to download
        debug: Whether to print debug information
        prefer_hd: If True, prefer 720p resolution; if False, get highest resolution
        skip_ids: Optional list of video IDs to skip
    """
    # Initialize skip_ids to empty list if None
    if skip_ids is None:
        skip_ids = []
    client = get_vimeo_client()
    
    # Create the download directory if it doesn't exist
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    
    try:
        if video_id:
            # Download a specific video
            response = client.get(f"/videos/{video_id}")
            
            if response.status_code != 200:
                click.echo(f"Error fetching video {video_id}: {response.text}")
                return
            
            videos = [response.json()]
        else:
            # Download all videos
            videos = list_videos()
        
        if not videos:
            return
        
        # Limit the number of videos to download if count is specified
        if count is not None and count > 0:
            videos = videos[:count]
            click.echo(f"Limiting download to {count} videos")
        
        # Check if we have permission to download videos
        click.echo("Checking download permissions...")
        
        # Download each video
        for video in videos:
            video_id = video["uri"].split("/")[-1]
            video_name = video["name"]
            
            # Skip this video if its ID is in the skip list
            if video_id in skip_ids:
                click.echo(f"\nSkipping video: {video_name} (ID: {video_id}) as requested")
                continue
                
            click.echo(f"\nProcessing video: {video_name} (ID: {video_id})")
            
            # Get the download link
            download_link = get_best_download_link(video, client, debug, prefer_hd)
            
            if not download_link:
                click.echo(f"No download link available for {video_name}. This could be due to:")
                click.echo("  - You don't have download permission for this video")
                click.echo("  - The video owner has disabled downloads")
                click.echo("  - The video is still being processed by Vimeo")
                click.echo("Skipping this video.")
                continue
            
            # Create a safe filename
            safe_name = "".join(c if c.isalnum() or c in " ._-" else "_" for c in video_name)
            file_ext = download_link["type"].split("/")[-1]
            filename = f"{safe_name}_{video_id}.{file_ext}"
            file_path = DOWNLOAD_DIR / filename
            
            # Check if the file already exists
            if file_path.exists():
                click.echo(f"File already exists: {file_path}. Skipping.")
                continue
            
            # Download the file
            click.echo(f"Downloading {video_name} ({download_link.get('width', 'unknown')}x{download_link.get('height', 'unknown')}, "
                       f"{download_link.get('size', 0) / (1024 * 1024):.2f} MB)...")
            
            # Print the download URL in debug mode
            if debug:
                click.echo("\n=== DOWNLOAD URL ===")
                click.echo(f"Download URL: {download_link['link']}")
                click.echo("=== END DOWNLOAD URL ===\n")
            
            response = requests.get(download_link["link"], stream=True)
            
            if response.status_code != 200:
                click.echo(f"Error downloading {video_name}: {response.status_code} {response.reason}")
                continue
                
            total_size = int(response.headers.get("content-length", 0))
            
            with open(file_path, "wb") as f, tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
            ) as progress_bar:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        progress_bar.update(len(chunk))
            
            click.echo(f"Downloaded: {file_path}")
        
        click.echo("\nDownload complete!")
        
    except Exception as e:
        click.echo(f"Error downloading videos: {e}")
        sys.exit(1)


@click.group()
def cli():
    """Vimeo Downloader - Connect to Vimeo, list and download videos."""
    pass


@cli.command()
def auth():
    """Authenticate with Vimeo using OAuth2."""
    authenticate()
    click.echo("Authentication successful!")


@cli.command()
@click.option("--limit", type=int, help="Limit the number of videos to list")
def list(limit):
    """List all videos in your Vimeo account."""
    list_videos(limit)


def parse_skip_ids(ctx, param, value):
    """Parse the skip IDs from a comma-separated string."""
    if not value:
        return []
    # Split by comma and strip whitespace from each ID
    return [id.strip() for id in value.split(',')]

@cli.command()
@click.option("--video-id", help="Download a specific video by ID")
@click.option("--count", type=int, help="Limit the number of videos to download")
@click.option("--debug", is_flag=True, help="Enable debug output with full JSON responses")
@click.option("--highest-quality", is_flag=True, help="Download highest quality instead of 720p")
@click.option("--skip", callback=parse_skip_ids, help="Comma-separated list of video IDs to skip (e.g., '123456,789012')")
def download(video_id, count, debug, highest_quality, skip):
    """Download videos from your Vimeo account."""
    download_video(video_id, count, debug, not highest_quality, skip)


if __name__ == "__main__":
    cli()
