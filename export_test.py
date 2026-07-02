import requests
import json
import os

# generate lecture
body = {
    "topic": "Photosynthesis",
    "course_level": "Undergraduate (Introductory)",
    "pages_count": 3,
    "additional_instructions": "Make slides student-friendly; include examples.",
    "include_media": True,
    "theme": "Modern Minimalist"
}

res = requests.post('http://127.0.0.1:8000/api/generate-lecture', json=body)
print('Generate status', res.status_code)
try:
    j = res.json()
except Exception as e:
    print('JSON decode failed', e, res.text)
    raise
print('Slides count', len(j.get('slides', [])))
print('Slide sample:', j.get('slides', [])[:1])

# export PPTX
pkg = {"slides": j.get('slides', []), "theme": body['theme']}
res2 = requests.post('http://127.0.0.1:8000/api/export-pptx', json=pkg)
print('Export status', res2.status_code)

if res2.status_code == 200:
    path = os.path.join(os.getcwd(), 'test_output.pptx')
    with open(path, 'wb') as f:
        f.write(res2.content)
    print('Saved pptx to', path)
else:
    print('Export error', res2.text)
