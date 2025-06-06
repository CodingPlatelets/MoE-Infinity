from openai import OpenAI

openai_api_key = "EMPTY"
openai_api_base = "http://localhost:8000/v1"
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)
completion = client.completions.create(
    model="deepseek-ai/DeepSeek-V2-Lite-Chat",
    prompt="Write a story about a cat.",
)
print("Completion result:", completion)
