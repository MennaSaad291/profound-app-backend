import os
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY_LECTURE"))
models = client.models.list()
for m in sorted(models.data, key=lambda x: x.id):
    print(m.id)
