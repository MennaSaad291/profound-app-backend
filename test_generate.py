import asyncio
from main import generate_lecture, LectureRequest


async def run():
	req = LectureRequest(topic="Photosynthesis", course_level="Undergraduate (Introductory)", pages_count=5, additional_instructions="Make slides student-friendly; include examples.", include_media=True, theme="Modern Minimalist")
	res = await generate_lecture(req)
	print("Slides returned:", len(res.get('slides', [])))
	if res.get('slides'):
		first = res['slides'][0]
		print('First slide title:', first.get('title'))
		print('First slide content (truncated):', first.get('content', [])[0][:200])


if __name__ == '__main__':
	asyncio.run(run())
