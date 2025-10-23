"""
Watcher Service (Self-Learning)
-------------------------------
Monitors Firestore for resolved help requests,
frames them into clean Q/A entries using Gemini,
and saves them to the knowledge_base collection.
"""

from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from dotenv import load_dotenv
import os
import time
import json

# === Setup ===
load_dotenv(".env")

cred = credentials.Certificate("firebase_service.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

print("🔥 Firestore connected and Gemini initialized")

# === Helper: Ask Gemini to frame a knowledge base entry ===
def generate_kb_entry(question: str, answer: str):
    prompt = f"""
    You are maintaining an internal knowledge base for a salon named Luxe Glow Salon.

    I will give you a resolved help request (a question and its answer).
    Your task is to:
    1. Rewrite the question clearly and concisely.
    2. Rewrite the answer naturally (like a helpful receptionist would say).
    3. Suggest 3–6 relevant lowercase keywords for matching future questions.
    4. Return valid JSON with keys: question, answer, keywords.

    Example format:
    {{
        "question": "Do you provide bridal makeup?",
        "answer": "Yes, we offer bridal makeup packages starting from $200.",
        "keywords": ["bridal", "makeup", "wedding"]
    }}

    Now here is the input:
    Question: {question}
    Answer: {answer}
    """

    try:
        model = genai.GenerativeModel("models/gemini-2.0-flash-exp")
        response = model.generate_content(prompt)
        text = (response.text or "").strip()

        if not text:
            raise ValueError("Gemini returned empty response")

        # Attempt to extract JSON even if it's surrounded by markdown/code blocks
        text = text.replace("```json", "").replace("```", "").strip()

        kb_entry = json.loads(text)
        return kb_entry

    except Exception as e:
        print("[ERROR] Gemini framing failed:", e)
        # Log what Gemini returned to help debugging
        if 'text' in locals():
            print("⚠️ Gemini raw output:", repr(text))

        # Fallback basic entry
        return {
            "question": question.strip(),
            "answer": answer.strip(),
            "keywords": [],
        }

# === Firestore watcher callback ===
def on_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == "MODIFIED":
            doc = change.document.to_dict()
            if doc.get("status") == "resolved":
                question = doc.get("question", "")
                answer = doc.get("answer", "")
                print(f"[SUPERVISOR REPLY] {question} → {answer}")

                # --- Use Gemini to frame KB entry ---
                kb_entry = generate_kb_entry(question, answer)

                # --- Add timestamp and save to Firestore ---
                kb_entry["learned_at"] = datetime.now().isoformat()
                db.collection("knowledge_base").add(kb_entry)
                print(f"[LEARNED] Added to knowledge_base ✅ {kb_entry['question']}")


# === Start watching ===
db.collection("help_requests").on_snapshot(on_snapshot)
print("👀 Watching Firestore for supervisor answers...")

# Keep running
while True:
    time.sleep(60)
