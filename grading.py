import random

def grade_text(text: str):

    word_count = len(text.split())

    if word_count > 800:
        return random.randint(85, 95)

    if word_count > 400:
        return random.randint(70, 85)

    return random.randint(50, 70)
