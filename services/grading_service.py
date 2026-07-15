import os
import json
from groq import Groq
import re

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY_GRADING"))
    return _client


def extract_json_from_response(text: str) -> dict:
    """
    Extract JSON from AI response that may contain markdown or descriptive text.
    """
    json_match = re.search(r'```json\s*({.*?})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except:
            pass

    json_match = re.search(r'({.*})', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except:
            pass

    try:
        return json.loads(text)
    except:
        pass

    print(f"Failed to parse AI response: {text[:200]}...")
    return {
        "score_out_of_100": 0,
        "summary": "Error parsing AI response.",
        "strengths": [],
        "areas_for_improvement": [],
        "error_categories": {},
        "recommendation": "",
        "detected_language": "Unknown"
    }


def perform_nlp_grading(student_text: str, mode: str, reference: str, feedback_tone: str = "formal"):
    """
    Grade a student submission and return a rich structured feedback report.
    feedback_tone options: "formal" | "encouraging" | "strict"
    """
    print(f"Detected Mode: {mode} | Tone: {feedback_tone}")

    tone_instructions = {
        "formal": (
            "Use a professional and neutral academic tone. "
            "Be precise and objective in your feedback."
        ),
        "encouraging": (
            "Use a warm, supportive tone. Acknowledge student effort, "
            "highlight positives before addressing gaps, and motivate improvement."
        ),
        "strict": (
            "Use a rigorous and direct tone. Be thorough in identifying all gaps "
            "and hold the student to a high academic standard."
        ),
    }
    tone_note = tone_instructions.get(feedback_tone, tone_instructions["formal"])

    json_schema = """
{
  "score_out_of_100": integer,
  "summary": "2-3 sentence overall assessment",
  "strengths": ["list of 2-4 specific things the student did well"],
  "areas_for_improvement": ["list of 2-4 specific gaps or weaknesses"],
  "error_categories": {
    "conceptual": "brief note on conceptual understanding (or null if none)",
    "structural": "brief note on structure/organization (or null if none)",
    "language": "brief note on language/clarity (or null if none)",
    "completeness": "brief note on coverage of required points (or null if none)"
  },
  "recommendation": "one actionable sentence the student should do next",
  "detected_language": "string"
}
"""

    # =========================
    # MODEL ANSWER MODE (SMART)
    # =========================
    if mode == "MODEL":
        system_prompt = f"""
You are an expert academic grader utilizing SEMANTIC UNDERSTANDING grading.

TONE: {tone_note}

GOAL:
Evaluate the student answer based on meaning, concepts, and correctness against the reference answer.

RULES:
- Do NOT penalize wording or sentence structure differences — focus on meaning and logic.
- Accept synonyms and paraphrases. Same idea with different wording → FULL CREDIT.
- Minor missing details → small deduction. Missing key ideas → medium deduction.
- If a student explicitly contradicts a key concept from the reference answer, apply a significant deduction. A contradiction is worse than omission.

SCORING GUIDE:
- 90-100: Correct meaning and logic, well-structured.
- 70-89: Mostly correct with minor gaps.
- 40-69: Partially correct, key ideas missing.
- 0-39: Incorrect or fundamentally misunderstood.
- If the student's answer is completely empty, blank, or contains only random gibberish/nonsense characters, you MUST score it exactly 0.

RETURN ONLY VALID JSON. Do NOT include any explanations or markdown code blocks outside the object.
The JSON output must strictly follow this structure:
{json_schema}
"""

    # =========================
    # RUBRIC MODE (SMART)
    # =========================
    else:
        system_prompt = f"""
You are an expert academic grader utilizing RUBRIC BASED evaluation.

TONE: {tone_note}

GOAL:
Evaluate the student answer using only the provided rubric criteria.

RULES:
- Do NOT compare exact text or require specific terminology.
- Evaluate each criterion independently (Fully Satisfied, Partially Satisfied, Not Satisfied).
- Calculate the score proportionally: Fully satisfied -> full marks; Partially satisfied -> partial marks; Missing criteria -> zero marks.
- If the student's answer is completely empty, blank, or contains only random gibberish, you MUST score it exactly 0.

RETURN ONLY VALID JSON. Do NOT include any explanations or markdown code blocks outside the object.
The JSON output must strictly follow this structure:
{json_schema}
"""

    user_content = f"""
REFERENCE:
{reference}

STUDENT ANSWER:
{student_text}
"""

    try:
        response = _get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            timeout=45
        )
        raw = response.choices[0].message.content
        print("RAW RESPONSE:", raw[:500])

        data = extract_json_from_response(raw)

        # Build consistent result payload maintaining required key metrics
        result = {
            "score_out_of_100":      data.get("score_out_of_100", 50),
            "summary":               data.get("summary", "Analysis complete."),
            "plagiarism":            0,  # Updated upstream by main.py checking logic
            "plagiarism_matches":    [],
            "detected_language":     data.get("detected_language", "English"),
            "strengths":             data.get("strengths", []),
            "areas_for_improvement": data.get("areas_for_improvement", data.get("improvements", [])),
            "error_categories":      data.get("error_categories", {}),
            "recommendation":        data.get("recommendation", ""),
            "feedback_tone":         feedback_tone,
        }

        print(f"✅ Parsed result: Score={result['score_out_of_100']}, Language={result['detected_language']}")
        return result

    except Exception as e:
        print(f"❌ Groq API Error: {e}")
        return {
            "score_out_of_100":      0,
            "summary":               f"Error during AI processing: {str(e)}",
            "plagiarism":            0,
            "plagiarism_matches":    [],
            "detected_language":     "Unknown",
            "strengths":             [],
            "areas_for_improvement": [],
            "error_categories":      {},
            "recommendation":        "",
            "feedback_tone":         feedback_tone,
        }