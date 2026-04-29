import os
import json
from groq import Groq
import re

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def safe_parse_ai_response(text: str):
    cleaned = re.sub(r"```json|```", "", text).strip()
    return json.loads(cleaned)

def perform_nlp_grading(student_text: str, mode: str, reference: str):

    print(f"Detected Mode: {mode}")

    # =========================
    # MODEL ANSWER MODE (SMART)
    # =========================
    if mode == "MODEL":

        system_prompt = """
        You are an intelligent academic grader.

        MODE: SEMANTIC UNDERSTANDING GRADING

        TASK:
        Evaluate the STUDENT ANSWER against the REFERENCE answer.

        IMPORTANT RULES:
        - DO NOT compare exact words or phrasing
        - DO NOT penalize different wording
        - Focus on meaning and logic only

        WHAT TO CHECK:
        1. Concept correctness
        2. Logical equivalence
        3. Coverage of key ideas

        GRADING LOGIC:
        - Same idea with different wording → FULL CREDIT
        - Same logic but different structure → FULL CREDIT
        - Minor missing details → small deduction
        - Missing key ideas → medium deduction
        - Wrong concepts → heavy deduction

        SPECIAL CASES:
        - Programming: correct logic = high score (even if syntax/style differs)
        - Theory: same meaning = high score
        - Short answers: concise correct answers are OK

        SCORING:
        - 90–100: same meaning / correct logic
        - 70–89: mostly correct
        - 40–69: partially correct
        - 0–39: incorrect

        RETURN ONLY VALID JSON:
        {
          "score_out_of_100": int,
          "summary": string
        }
        """

    # =========================
    # RUBRIC MODE (SMART)
    # =========================
    else:

        system_prompt = """
        You are an intelligent academic grader.

        MODE: RUBRIC BASED EVALUATION

        TASK:
        Evaluate the student answer based ONLY on the rubric.

        IMPORTANT:
        - Do NOT compare wording
        - Focus on whether the student satisfies rubric criteria
        - Accept equivalent explanations

        STEPS:
        1. Identify rubric criteria
        2. Check how many are satisfied
        3. Assign score proportionally

        RULES:
        - Partial satisfaction → partial score
        - Full satisfaction → high score
        - Missing criteria → reduce score

        RETURN ONLY VALID JSON:
        {
          "score_out_of_100": int,
          "summary": string
        }
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
            timeout=30  # ⬅️ ADD THIS
        )
        raw = response.choices[0].message.content
        print("RAW RESPONSE:", raw)

        # ✅ CLEAN MARKDOWN WRAPPING
        cleaned = re.sub(r"```json|```", "", raw).strip()

        data = json.loads(cleaned)

        return {
            "score_out_of_100": data.get("score_out_of_100", 50),
            "summary": data.get("summary", "")
        }

    except Exception as e:
        print(f"Groq API Error: {e}")

        return {
            "score_out_of_100": 0,
            "summary": "Error during AI processing."
        }