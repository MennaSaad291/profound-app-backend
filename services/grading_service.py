import os
import json
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def perform_nlp_grading(student_text: str, rubric_description: str):
    system_prompt = """
    You are an AI Academic Grader. Analyze the text based on these 4 criteria:
    1. Content & Understanding (Max 25)
    2. Structure & Organization (Max 25)
    3. Technical Accuracy (Max 25)
    4. Writing Quality (Max 25)

    Return ONLY a JSON object with:
    - score_out_of_100: (int)
    - criteria_scores: { 
        "content": int, 
        "structure": int, 
        "technical": int, 
        "writing": int 
      }
    - strengths: [list]
    - improvements: [list]
    - summary: (string)
    """

    user_content = f"Rubric/Assignment: {rubric_description}\n\nStudent Work: {student_text}"

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error calling Groq API: {e}")
        return {
            "score_out_of_100": 0,
            "criteria_scores": {"grammar": 0, "relevance": 0, "depth": 0},
            "strengths": [],
            "improvements": ["Error connecting to AI service"],
            "summary": "Grading failed due to an external API error."
        }