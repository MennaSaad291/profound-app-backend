import os
import json
from groq import Groq
import re

client = Groq(api_key=os.getenv("GROQ_API_KEY_GRADING"))


def safe_parse_ai_response(text: str):
    cleaned = re.sub(r"```json|```", "", text).strip()
    return json.loads(cleaned)


def perform_nlp_grading(student_text: str, mode: str, reference: str, feedback_tone: str = "formal"):
    """
    Grade a student submission and return a rich structured feedback report.

    feedback_tone options: "formal" | "encouraging" | "strict"
    """

    print(f"Detected Mode: {mode} | Tone: {feedback_tone}")

    # ── Tone instruction injected into both prompts ───────────────────────
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

    # ── JSON schema expected from the AI ─────────────────────────────────
    json_schema = """
{
  "score_out_of_100": int,
  "summary": "2-3 sentence overall assessment",
  "strengths": ["list of 2-4 specific things the student did well"],
  "areas_for_improvement": ["list of 2-4 specific gaps or weaknesses"],
  "error_categories": {
    "conceptual": "brief note on conceptual understanding (or null if none)",
    "structural": "brief note on structure/organization (or null if none)",
    "language": "brief note on language/clarity (or null if none)",
    "completeness": "brief note on coverage of required points (or null if none)"
  },
  "recommendation": "one actionable sentence the student should do next"
}
"""

    # ── MODEL ANSWER MODE ─────────────────────────────────────────────────
    if mode == "MODEL":
        system_prompt = f"""
You are an intelligent academic grader using SEMANTIC UNDERSTANDING grading.

TONE: {tone_note}

TASK:
Evaluate the STUDENT ANSWER against the REFERENCE answer.

RULES:
- Do NOT penalize different wording — focus on meaning and logic
- Same idea with different wording → FULL CREDIT
- Minor missing details → small deduction
- Missing key ideas → medium deduction
- Wrong concepts → heavy deduction

SCORING GUIDE:
- 90-100: Correct meaning and logic, well-structured
- 70-89: Mostly correct with minor gaps
- 40-69: Partially correct, key ideas missing
- 0-39: Incorrect or fundamentally misunderstood

RETURN ONLY VALID JSON matching this exact schema:
{json_schema}
"""

    # ── RUBRIC MODE ───────────────────────────────────────────────────────
    else:
        system_prompt = f"""
You are an intelligent academic grader using RUBRIC-BASED evaluation.

TONE: {tone_note}

TASK:
Evaluate the student answer based ONLY on the provided rubric criteria.

RULES:
- Do NOT compare wording
- Check whether each rubric criterion is satisfied
- Partial satisfaction → partial score
- Full satisfaction → high score
- Missing criteria → reduce score proportionally

RETURN ONLY VALID JSON matching this exact schema:
{json_schema}
"""

    user_content = f"""
REFERENCE:
{reference}

STUDENT ANSWER:
{student_text}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
            timeout=45
        )
        raw = response.choices[0].message.content
        print("RAW RESPONSE:", raw)

        cleaned = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(cleaned)

        return {
            "score_out_of_100":      data.get("score_out_of_100", 50),
            "summary":               data.get("summary", ""),
            "strengths":             data.get("strengths", []),
            "areas_for_improvement": data.get("areas_for_improvement", []),
            "error_categories":      data.get("error_categories", {}),
            "recommendation":        data.get("recommendation", ""),
            "feedback_tone":         feedback_tone,
        }

    except Exception as e:
        print(f"Groq API Error: {e}")
        return {
            "score_out_of_100":      0,
            "summary":               "Error during AI processing.",
            "strengths":             [],
            "areas_for_improvement": [],
            "error_categories":      {},
            "recommendation":        "",
            "feedback_tone":         feedback_tone,
        }
