import os, time
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"), transport="rest")
model = genai.GenerativeModel("gemini-3.5-flash-lite")

t = time.time()
try:
    r = model.generate_content("hi", request_options={"retry": None, "timeout": 20})
    print("OK:", r.text, f"({time.time() - t:.1f}s)")
except Exception as e:
    print("FAILED:", type(e).__name__, e, f"({time.time() - t:.1f}s)")