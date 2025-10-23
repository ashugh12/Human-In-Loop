"""
LiveKit Voice Agent - Fake Salon Assistant
==========================================
Step 4.4: Gemini Realtime + Firestore + Smart Supervisor Escalation
"""

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RunContext
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, silero, google
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import asyncio
import google.generativeai as genai
import os

# === Load environment variables ===
load_dotenv(".env")

# === Initialize Firebase ===
cred = credentials.Certificate("firebase_service.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
print("🔥 Connected to Firebase project:", db._database_string)

# === Configure Gemini ===
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


# ==========================================================
#                      AGENT CLASS
# ==========================================================
class SalonAgent(Agent):
    """Friendly salon receptionist with Gemini Realtime + Smart Firestore escalation."""

    def __init__(self):
        super().__init__(
            instructions="""
            You are a friendly receptionist for a salon named 'Luxe Glow Salon'.
            You can help customers with:
            - Booking appointments
            - Providing salon hours, address, and services.

            You have access to:
            1. `search_knowledge_base` — checks known questions/answers from Firestore.
            2. `handle_unknown_question` — logs unresolved questions to Firestore for supervisor help.

            When a user asks something, always:
            - First, try to find the answer using `search_knowledge_base`.
            - If not found, call `handle_unknown_question`.
            - Never guess an answer.

            Keep your tone warm, polite, and concise.
            """
        )

        self.knowledge_base_static = {
            "hours": "We are open from 9 AM to 8 PM, Monday through Saturday.",
            "address": "123 Main Street, Springfield.",
            "services": "We offer haircut, hair coloring, facial, and manicure services.",
            "contact": "You can reach us at +1 555-123-4567.",
        }

        self.response_timer = None
        self.last_user_message = None

    # ==========================================================
    #           GEMINI REPHRASER FOR SUPERVISOR CLARITY
    # ==========================================================
    async def clarify_for_supervisor(self, question: str) -> str:
        """Uses Gemini to rephrase a vague question into a clear supervisor query."""
        prompt = f"""
        The following is a vague or short customer question for Luxe Glow Salon:

        "{question}"

        Please rewrite it so that a human salon supervisor immediately understands what
        the customer is asking about — such as whether it's about a service, price, or appointment.

        The rephrased version should:
        - Be 1–2 sentences max.
        - Mention 'Luxe Glow Salon' if relevant.
        - Be polite, clear, and specific.
        - Avoid AI or chatbot references.

        Examples:
        "bridal?" → "The customer is asking if Luxe Glow Salon offers bridal makeup packages and their prices."
        "Do you do animal?" → "The customer is asking whether Luxe Glow Salon provides makeup or grooming services for animals."

        Now rewrite the question appropriately.
        """

        try:
            model = genai.GenerativeModel("models/gemini-2.0-flash-exp")
            response = model.generate_content(prompt)
            clarified = (response.text or "").strip()
            if not clarified:
                clarified = question
            print(f"[CLARIFIED] {question} → {clarified}")
            return clarified
        except Exception as e:
            print("[ERROR] Clarify failed:", e)
            return question

    # ==========================================================
    #            FIRESTORE KNOWLEDGE BASE LOOKUP (AS TOOL)
    # ==========================================================
    @function_tool
    async def search_knowledge_base(self, context: RunContext, question: str) -> str:
        """Search Firestore 'knowledge_base' for matching Q/A by keyword or substring."""
        try:
            docs = db.collection("knowledge_base").stream()
            q_lower = question.lower()

            for doc in docs:
                data = doc.to_dict()
                stored_q = data.get("question", "").lower()
                stored_a = data.get("answer", "")
                keywords = [kw.lower() for kw in data.get("keywords", [])]

                # Direct match
                if stored_q in q_lower or q_lower in stored_q:
                    print(f"[KB HIT] Exact match: '{stored_q}' → '{stored_a}'")
                    return stored_a

                # Keyword match
                if any(kw in q_lower for kw in keywords):
                    print(f"[KB HIT] Keyword match: {keywords} → '{stored_a}'")
                    return stored_a

            print("[KB MISS] No relevant knowledge found.")
            return "Not found"

        except Exception as e:
            print("[ERROR] Knowledge base lookup failed:", e)
            return "Not found"

    # ==========================================================
    #                 FIRESTORE ESCALATION
    # ==========================================================
    @function_tool
    async def handle_unknown_question(self, context: RunContext, question: str) -> str:
        """Triggered when Gemini or timeout cannot find an answer."""
        print(f"[ESCALATION] Supervisor help requested for: '{question}'")

        clarified_question = await self.clarify_for_supervisor(question)

        doc = {
            "raw_question": question,
            "clarified_question": clarified_question,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        try:
            db.collection("help_requests").add(doc)
            print(f"[DEBUG] Logged to Firestore ✅ Clarified: {clarified_question}")
        except Exception as e:
            print("[ERROR] Firestore log failed:", e)

        return (
            "Let me check with my supervisor and get back to you. "
            "They’ll be able to provide the most accurate information."
        )

    # ==========================================================
    #                      TIMEOUT FALLBACK
    # ==========================================================
    async def start_timeout(self, message: str, context: RunContext):
        """If Gemini does not reply within 10s, trigger escalation automatically."""
        if self.response_timer and not self.response_timer.done():
            self.response_timer.cancel()

        async def timeout():
            await asyncio.sleep(10)
            print("[TIMEOUT] No response from Gemini within 10s.")
            await self.handle_unknown_question(context, message)
            await context.send_text("Let me check with my supervisor and get back to you.")

        self.response_timer = asyncio.create_task(timeout())

    # ==========================================================
    #                      EVENT HANDLERS
    # ==========================================================
    async def on_text_message(self, message: str, context: RunContext):
        print(f"[USER SAID] {message}")
        self.last_user_message = message
        text = message.lower()

        # Step 1: Static replies
        if any(k in text for k in ["hour", "open", "close"]):
            await context.send_text(self.knowledge_base_static["hours"])
            return
        elif any(k in text for k in ["address", "location"]):
            await context.send_text(self.knowledge_base_static["address"])
            return
        elif any(k in text for k in ["service", "hair", "facial", "manicure", "price"]):
            await context.send_text(self.knowledge_base_static["services"])
            return

        # Step 2: Escalate via Gemini if unknown
        await self.start_timeout(message, context)


# ==========================================================
#                       ENTRY POINT
# ==========================================================
async def entrypoint(ctx: agents.JobContext):
    print("🚀 Starting Luxe Glow Salon Agent (Gemini Realtime)...")

    salon_agent = SalonAgent()

    session = AgentSession(
        stt=deepgram.STT(model="nova-2"),
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.0-flash-exp",
            api_key=os.getenv("GOOGLE_API_KEY"),
            voice="Puck",
            temperature=0.7,
            instructions="""
                 You are a friendly receptionist for Luxe Glow Salon.
                - Do NOT call any tools if the question is about hours, address, contact, or services. 
                  Just respond directly with known information.
                - Otherwise:
                    1. Call `search_knowledge_base` with the user's question.
                    2. If it returns "Not found", 
                       say “Let me check with my supervisor and get back to you,” 
                       and then call `handle_unknown_question` with that question.
                Keep your tone short, clear, and polite.
            """,
        ),
        tts=google.TTS(gender="female", voice_name="en-US-Standard-H"),
        vad=silero.VAD.load(),
    )

    # === Transcript listeners ===
    def on_transcript(event):
        asyncio.create_task(salon_agent.on_text_message(event.text, session))

    session.on("transcript", on_transcript)

    await session.start(room=ctx.room, agent=salon_agent)

    # === Firestore watcher for supervisor responses ===
    main_loop = asyncio.get_running_loop()

    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name == "MODIFIED":
                doc = change.document.to_dict()
                if doc.get("status") == "resolved":
                    question = doc.get("clarified_question") or doc.get("raw_question")
                    answer = doc.get("answer")
                    print(f"[SUPERVISOR ANSWER DETECTED] {question} → {answer}")

                    async def respond_to_supervisor_update():
                        try:
                            await session.generate_reply(
                                instructions=(
                                    f"My supervisor has shared an answer to your question. "
                                    f"Please tell the user in a warm and natural tone: {answer}"
                                )
                            )
                        except Exception as e:
                            print(f"[ERROR] Failed to generate Gemini reply: {e}")

                    main_loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(respond_to_supervisor_update())
                    )

    query = db.collection("help_requests")
    query.on_snapshot(on_snapshot)
    print("👂 Listening for supervisor updates in Firestore...")

    # Initial greeting
    await session.generate_reply(
        instructions="Greet the caller warmly and ask how you can assist them today."
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
