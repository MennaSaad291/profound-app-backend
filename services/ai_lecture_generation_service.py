import os
import json
import re
from groq import Groq
from fastapi import HTTPException

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_lecture_json(data):

    prompt = f"""
You are an expert university professor and instructional designer.

Generate a PROFESSIONAL academic lecture presentation.

LECTURE INFORMATION
Topic: {data.topic}
Academic Level: {data.course_level}
Number of Slides: {data.pages_count}

Professor Custom Instructions:
{getattr(data, "additional_instructions", "")}

------------------------------------------------
CONTENT RULES
------------------------------------------------

1. Slide Structure

Slide 1:
Title slide

Slide 2:
Lecture overview

Remaining slides should include:
- key concepts
- definitions
- explanations
- examples
- applications
- final summary

2. Bullet Point Rules

Each slide must contain:
- 4 to 6 bullet points
- each bullet must be short
- maximum 18 words per bullet
- no long paragraphs

3. Academic Quality

Content must reflect real university lecture quality.

When explaining a concept:
- give definition
- explain idea
- provide example if helpful

4. Image Policy

Images should be used ONLY when they help understanding.

Examples of useful images:
- diagrams
- workflows
- system architecture
- scientific processes
- comparisons

DO NOT add images to every slide.

Images should appear in about 20–30 percent of slides.

If needed include:

"image_suggestion": "short description of an educational diagram"

If no image needed:

"image_suggestion": null

5. Source Policy

If professor sources exist → prioritize them.

If no sources exist → rely on trusted academic knowledge such as:

- university textbooks
- peer reviewed research
- academic publications
- standard university curricula

Examples of trusted sources:
MIT OpenCourseWare
IEEE
ACM
Springer
Elsevier
Oxford academic books

DO NOT invent fake sources.

------------------------------------------------
JSON FORMAT
------------------------------------------------

Return strictly valid JSON:

{{
 "slides": [
   {{
     "title": "Slide Title",
     "content": [
       "bullet point",
       "bullet point",
       "bullet point"
     ],
     "image_suggestion": "diagram description or null",
     "speaker_notes": "short explanation for the professor"
   }}
 ]
}}

CRITICAL:
- JSON ONLY
- no markdown
- no explanations
- no extra text
"""

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You generate professional university lecture slides in strict JSON format."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        )

        raw = completion.choices[0].message.content

        match = re.search(r'\{.*\}', raw, re.DOTALL)

        if not match:
            raise HTTPException(status_code=500, detail="AI failed to generate valid JSON")

        return json.loads(match.group(0))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))