import os
import json
import re
from groq import Groq
from fastapi import HTTPException

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_lecture_json(data):
    prompt = f"""
    Generate a university lecture JSON for topic: {data.topic}.
    Slide Count: {data.pages_count}. Level: {data.course_level}.
    Format: {{ "slides": [ {{ "title": "...", "content": ["..."], "speaker_notes": "..." }} ] }}
    """
    
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "system", "content": "JSON-only academic generator."}, 
                  {"role": "user", "content": prompt}],
    )
    
    raw = completion.choices[0].message.content
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise HTTPException(status_code=500, detail="AI failed to generate valid JSON")
    
    return json.loads(match.group(0))