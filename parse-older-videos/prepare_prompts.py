"""
Helper script to prepare timestamp extraction prompts.

This script takes the improved template and fills it with reference and target
video data, making it ready to send to a large language model.
"""

import os
import sys


def load_file(filepath: str) -> str:
    """Load content from a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def extract_video_info(description_path: str) -> tuple[str, str, str]:
    """
    Extract title, URL, and timestamp section from a description file.
    
    Returns:
        (title, url, timestamps_section)
    """
    content = load_file(description_path)
    lines = content.split('\n')
    
    title = ""
    url = ""
    timestamps = []
    in_timestamps = False
    
    for line in lines:
        if line.startswith("Video: "):
            title = line.replace("Video: ", "").strip()
        elif line.startswith("URL: "):
            url = line.replace("URL: ", "").strip()
        elif "Questions and Timestamps:" in line or "Timestamps:" in line:
            in_timestamps = True
            timestamps.append(line)
        elif in_timestamps:
            # Stop at empty lines or obvious section breaks
            if line.strip() == "" and len(timestamps) > 2:
                # Multiple empty lines = end of timestamps
                if timestamps and timestamps[-1].strip() == "":
                    break
            timestamps.append(line)
    
    timestamps_section = '\n'.join(timestamps).strip()
    
    return title, url, timestamps_section


def prepare_prompt(
    template_path: str,
    reference_transcript: str,
    reference_description: str,
    target_video_title: str,
    target_video_url: str,
    target_transcript: str,
    output_path: str
):
    """
    Fill the template with actual data and save to output file.
    """
    template = load_file(template_path)
    
    # Replace placeholders
    filled_prompt = template.replace("{reference_transcript}", reference_transcript)
    filled_prompt = filled_prompt.replace("{reference_description}", reference_description)
    filled_prompt = filled_prompt.replace("{target_video_title}", target_video_title)
    filled_prompt = filled_prompt.replace("{target_video_url}", target_video_url)
    filled_prompt = filled_prompt.replace("{target_transcript}", target_transcript)
    
    # Save to output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(filled_prompt)
    
    print(f"✅ Saved prompt to: {output_path}")
    return filled_prompt


def main():
    """Generate prompts for each video without timestamps."""
    
    exports_dir = "exports"
    prompts_dir = "prompts"
    os.makedirs(prompts_dir, exist_ok=True)
    
    # Reference video (has good timestamps)
    reference_video_id = "qS8kiCWbZy0"
    reference_transcript_path = f"{exports_dir}/{reference_video_id}_transcript.txt"
    reference_description_path = f"{exports_dir}/{reference_video_id}_description.txt"
    
    print("📖 Loading reference video...")
    reference_title, reference_url, reference_timestamps = extract_video_info(reference_description_path)
    reference_transcript = load_file(reference_transcript_path)
    
    print(f"   Title: {reference_title}")
    print(f"   Found {len(reference_timestamps.split(chr(10)))} timestamp lines\n")
    
    # Videos that need timestamps
    target_videos = [
        "Q8rfyMrjlnI",
        "ucjegR-jiYo",
        "kCp0tkR7YYU",
        "6Ih9uEGeJBI",
    ]
    
    template_path = "extract timestamps prompt.md"
    
    print("=" * 80)
    print("Generating prompts for videos without timestamps...")
    print("=" * 80 + "\n")
    
    for video_id in target_videos:
        print(f"🎬 Processing {video_id}...")
        
        target_transcript_path = f"{exports_dir}/{video_id}_transcript.txt"
        target_description_path = f"{exports_dir}/{video_id}_description.txt"
        
        target_title, target_url, _ = extract_video_info(target_description_path)
        target_transcript = load_file(target_transcript_path)
        
        print(f"   Title: {target_title}")
        
        output_path = f"{prompts_dir}/{video_id}_prompt.md"
        
        prepare_prompt(
            template_path=template_path,
            reference_transcript=reference_transcript,
            reference_description=reference_timestamps,
            target_video_title=target_title,
            target_video_url=target_url,
            target_transcript=target_transcript,
            output_path=output_path
        )
        print()
    
    print("=" * 80)
    print("✅ All prompts generated!")
    print(f"📁 Check the '{prompts_dir}' directory")
    print("=" * 80)
    print("\n💡 Next steps:")
    print("   1. Open each prompt file in the prompts/ directory")
    print("   2. Copy the entire content")
    print("   3. Send to a large language model (Claude, GPT-4, Gemini 1.5 Pro, etc.)")
    print("   4. The model will output formatted timestamps")
    print("   5. Copy timestamps and paste into the video description on YouTube")


if __name__ == "__main__":
    main()
