import os
import json
import random
from groq import Groq
from typing import List
from schemas import ExamRequest, Question

class ExamGeneratorService:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    async def generate_exam_content(self, request: ExamRequest):
        """
        Generates questions aligned with Bloom's Taxonomy using Groq.
        """
        prompt = f"""
        Act as a University Professor. Generate {request.number_of_questions} {request.question_type} questions for: {request.topic}.
        Bloom's Taxonomy Level: {request.blooms_level}. Difficulty: {request.difficulty}.

        STRICT JSON STRUCTURE:
        Return ONLY a JSON object with a key "questions" containing a list of objects.
        Each object MUST use these exact keys:
        "question_text": (the question string)
        "question_type": "{request.question_type}"
        "options": (list of 4 strings for MCQ, or null for Essay)
        "correct_answer": (the correct answer string)
        "explanation": (why the answer is correct)
        "difficulty": "{request.difficulty}"
        """

        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a JSON-only academic exam generator."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        raw = completion.choices[0].message.content
        cleaned = raw.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned)

    @staticmethod
    def generate_variations(questions: List[dict], num_versions: int = 2):
        """
        Creates unique exam versions to minimize cheating.
        """
        variations = []
        for _ in range(num_versions):
            shuffled_version = list(questions)
            random.shuffle(shuffled_version)
            variations.append(shuffled_version)
        return variations