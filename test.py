import os
import re
import sys
import json
from typing import List, Optional
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('GOOGLE_API_KEY')
VIDEO_URL = 'https://www.youtube.com/watch?v=oGIqIuoBItQ'

# --- DATA MODELS ---
class Classification(BaseModel):
    category: str = Field(description="The main category from the provided list.")
    subcategory: str = Field(description="The subcategory from the provided list.")
    tags: List[str] = Field(description="A list of relevant tags or topics associated with the Q&A.")

class QuestionMatch(BaseModel):
    timestamp: str
    question: str
    answer: str
    classification: Optional[Classification] = None

def get_video_id(url):
    """Extracts video ID from URL (v=... or /live/...)"""
    regex = r"(?:v=|\/live\/|\/shorts\/|\/youtu\.be\/)([0-9A-Za-z_-]{11})"
    match = re.search(regex, url)
    if match: return match.group(1)
    raise ValueError("Could not extract Video ID")

def get_video_description(video_id, api_key):
    """Fetches description using Official Google API"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if not response['items']:
            print("Error: Video not found by Official API.")
            return ""
        return response['items'][0]['snippet']['description']
    except Exception as e:
        print(f"API Error: {e}")
        return ""

def parse_description_timestamps(description_text):
    """Parses 'Time - Question' or 'Question - Time'"""
    questions = []
    time_pattern = r"(\d{1,2}:\d{2}(?:\:\d{2})?)" # Matches 00:00 or 1:00:00
    
    for line in description_text.split('\n'):
        line = line.strip()
        if not line: continue
        
        # Check timestamp at START ("04:20 Question text")
        match_start = re.match(f"^{time_pattern}", line)
        if match_start:
            timestamp = match_start.group(1)
            text = line[match_start.end():].strip(" -|.")
            questions.append({'time': timestamp, 'question': text})
            continue
            
        # Check timestamp at END ("Question text 04:20")
        match_end = re.search(f"{time_pattern}$", line)
        if match_end:
            timestamp = match_end.group(1)
            text = line[:match_end.start()].strip(" -|.")
            questions.append({'time': timestamp, 'question': text})
            
    return questions

def get_raw_transcript(video_id):
    """
    Fetches raw transcript data (list of dictionaries).
    """
    try:
        yt = YouTubeTranscriptApi()
        transcript_list = yt.list(video_id)
        
        try:
            transcript = transcript_list.find_transcript(['en'])
        except:
            transcript = transcript_list.find_generated_transcript(['en'])
            
        return transcript.fetch()
        
    except Exception as e:
        print(f"Transcript Error: {e}")
        return None

def match_questions_to_transcript(questions, transcript_data):
    """
    questions: List of {'time': '19:38', 'question': '...'}
    transcript_data: Raw list from .fetch() [{'start': 1178.0, 'text': '...'}]
    """
    
    # Helper to convert "MM:SS" string to Seconds (float)
    def time_str_to_seconds(time_str):
        parts = list(map(int, time_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2] # HH:MM:SS
        return parts[0]*60 + parts[1] # MM:SS

    # Add 'seconds' key to your questions for easier comparison
    for q in questions:
        q['seconds'] = time_str_to_seconds(q['time'])

    # Sort questions by time just in case
    questions.sort(key=lambda x: x['seconds'])
    
    results = []
    
    for i, q in enumerate(questions):
        # Define the start and end time for this question
        start_time = q['seconds']
        
        # End time is the start of the NEXT question, or Infinity if it's the last one
        if i + 1 < len(questions):
            end_time = questions[i+1]['seconds']
        else:
            end_time = float('inf')
            
        # Collect all transcript lines that fit in this window
        answer_text = []
        for line in transcript_data:
            # Handle object access (FetchedTranscriptSnippet)
            if line.start >= start_time and line.start < end_time:
                answer_text.append(line.text)
        
        results.append({
            'timestamp': q['time'],
            'question': q['question'],
            'answer': " ".join(answer_text)
        })
        
    return results

def load_categories(filepath="categories.json"):
    if not os.path.exists(filepath):
        print(f"Warning: {filepath} not found.")
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def classify_question(question_text, answer_text, categories_context):
    """
    Classifies a Q&A pair using Gemini and the provided categories.
    """
    # Use GEMINI_API_KEY strictly for Gemini calls
    gemini_key = os.getenv('GEMINI_API_KEY')
    
    if not gemini_key:
        print("Error: GEMINI_API_KEY not found in environment variables.")
        return None

    try:
        client = genai.Client(api_key=gemini_key)
        
        # Summarize large answer text if needed to save tokens, though 1.5 has large context
        snippet = answer_text[:2000] # simple truncation if massive
        
        prompt = f"""
        You are a theological assistant. Classify the following Q&A based on the provided categories.
        
        Categories Structure:
        {json.dumps(categories_context)}
        
        Question: {question_text}
        Answer: {snippet}
        
        Please assign a Category, Subcategory from the list provided, and generate a list of relevant Tags.
        If the content doesn't fit perfectly, choose the best fit.
        """
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": Classification.model_json_schema(),
            },
        )
        json_text = response.text
        if not json_text:
            print("Classification returned empty response.")
            return None
        return Classification.model_validate_json(json_text)
    except Exception as e:
        print(f"Classification Error: {e}")
        return None

# --- MAIN ---
if __name__ == "__main__":
    # Ensure output directory exists
    OUT_DIR = "out"
    os.makedirs(OUT_DIR, exist_ok=True)

    # Check Python version to ensure environment is sound
    print(f"Python: {sys.version.split()[0]}")
    
    vid_id = get_video_id(VIDEO_URL)
    print(f"Processing ID: {vid_id}")
    
    # 1. Get Questions
    desc_path = os.path.join(OUT_DIR, "description.txt")
    
    # Check if we have it in CWD (legacy) or OUT_DIR, or fetch
    if os.path.exists(desc_path):
        print(f"Reading description from '{desc_path}'...")
        with open(desc_path, "r", encoding="utf-8") as f:
            desc = f.read()
    elif os.path.exists("description.txt"): # Fallback to CWD
         print("Reading description from 'description.txt'...")
         with open("description.txt", "r", encoding="utf-8") as f:
            desc = f.read()
    else:
        print("Fetching description...")
        desc = get_video_description(vid_id, API_KEY)
        # Save description to file
        with open(desc_path, "w", encoding="utf-8") as f:
            f.write(desc)
        print(f"Saved description to '{desc_path}'")

    questions = parse_description_timestamps(desc)
    print(f"Found {len(questions)} timestamps.")
    
    # 2. Get Transcript
    print("Fetching transcript...")
    transcript_data = get_raw_transcript(vid_id)
    
    if transcript_data:
        print(f"\nSUCCESS! Transcript retrieved ({len(transcript_data)} segments).")
        
        # Save timestamped transcript
        formatted_lines = []
        for line in transcript_data:
            minutes = int(line.start // 60)
            seconds = int(line.start % 60)
            timestamp_str = f"[{minutes:02}:{seconds:02}]"
            formatted_lines.append(f"{timestamp_str} {line.text}")
        
        transcript_path = os.path.join(OUT_DIR, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(formatted_lines))
        print(f"Saved timestamped transcript to '{transcript_path}'")

        # 3. Match Questions to Text
        if questions:
            matches = match_questions_to_transcript(questions, transcript_data)
            print(f"Matched {len(matches)} questions.")
            
            # --- CLASSIFICATION START ---
            print("Loading categories...")
            categories = load_categories()
            
            final_results = []
            
            print("Classifying questions (this may take a moment)...")
            for m in matches:
                print(f"Classifying: {m['question'][:50]}...")
                cls = classify_question(m['question'], m['answer'], categories)
                
                # Construct result object using Pydantic model
                q_match = QuestionMatch(
                    timestamp=m['timestamp'],
                    question=m['question'],
                    answer=m['answer'],
                    classification=cls
                )
                final_results.append(q_match.model_dump())
                
            # Save classified JSON matches
            json_path = os.path.join(OUT_DIR, "qa_matches.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(final_results, f, indent=2, ensure_ascii=False)
            print(f"Saved Classified Q&A to '{json_path}'")
            # --- CLASSIFICATION END ---
            
    else:
        print("Failed to download transcript.")