import os
from googleapiclient.discovery import build

from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('GOOGLE_API_KEY')

# The playlist ID extracted from your URL
PLAYLIST_ID = 'PLczriqVOY-tll3hzb2O7jHwKaEV1kd2IJ'

def get_all_video_urls(api_key, playlist_id):
    """
    Retrieves and prints all video URLs from a specific YouTube playlist.
    """
    try:
        # Build the YouTube client using the library found in your requirements.txt
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        video_urls = []
        next_page_token = None
        
        print(f"Fetching videos for playlist ID: {playlist_id}...\n")
        
        while True:
            # Request the playlist items
            request = youtube.playlistItems().list(
                part='contentDetails',  # We only need the ID, so contentDetails is sufficient
                playlistId=playlist_id,
                maxResults=50,          # Max allowed per request
                pageToken=next_page_token
            )
            response = request.execute()
            
            # Extract video IDs and construct URLs
            for item in response.get('items', []):
                video_id = item['contentDetails']['videoId']
                video_url = f'https://www.youtube.com/watch?v={video_id}'
                video_urls.append(video_url)
                print(video_url)
            
            # Check if there is a next page
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

        print(f"\nTotal videos found: {len(video_urls)}")
        
        # Save to a text file
        with open('playlist_videos.txt', 'w') as f:
            for url in video_urls:
                f.write(f"{url}\n")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please check if your API KEY is valid and has YouTube Data API v3 enabled.")

if __name__ == '__main__':
    get_all_video_urls(API_KEY, PLAYLIST_ID)