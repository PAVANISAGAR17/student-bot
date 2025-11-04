# app.py
import re
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SimpleRealtimeChatbot")

# allow CORS for testing / mobile clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = "conversations.db"

# --- Simple DB helpers --- #
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        message TEXT,
        timestamp TEXT
    )
    """)
    conn.commit()
    conn.close()

def log_message(session_id: str, role: str, message: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (session_id, role, message, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, message, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

# initialize DB on import
init_db()

# --- Simple intent detection --- #
def detect_intent(text: str) -> Dict[str, Any]:
    t = text.lower().strip()
    # patterns for mobile network
    if re.search(r"\b(signal|network|no service|coverage|latency|slow data|dropped call)\b", t):
        return {"intent": "network_issue", "confidence": 0.9}
    if re.search(r"\b(balance|plan|data left|recharge|top[- ]up|bill)\b", t):
        return {"intent": "account_query", "confidence": 0.9}

    # health patterns
    if re.search(r"\b(symptom|fever|cough|pain|headache|nausea|shortness of breath)\b", t):
        return {"intent": "symptom_check", "confidence": 0.9}
    if re.search(r"\b(appointment|book appointment|doctor|visit|schedule)\b", t):
        return {"intent": "book_appointment", "confidence": 0.9}

    # utility
    if re.search(r"\b(hi|hello|hey|good morning|good evening)\b", t):
        return {"intent": "greeting", "confidence": 0.95}
    if re.search(r"\b(thank|thanks)\b", t):
        return {"intent": "thanks", "confidence": 0.95}

    return {"intent": "fallback", "confidence": 0.5}

# --- Intent handlers --- #
def handle_network_issue(text: str, context: Dict[str,Any]) -> str:
    # very simple diagnostic flow
    if re.search(r"\b(no service|no signal|no network)\b", text.lower()):
        return ("I understand you're seeing no network signal. Try: 1) toggle airplane mode off/on, "
                "2) restart your device, 3) check for network outages in your area. "
                "If the problem persists, reply with your area PIN or 'outage' to check further.")
    if re.search(r"\b(slow|latency|slow data)\b", text.lower()):
        return ("Slow data can be caused by congestion. Try switching between 4G/3G, "
                "closing background apps, or running a speed test. Want me to run a quick diagnostic?")

    return ("Can you describe the network problem (e.g., no signal, slow data, dropped calls)?")

def handle_account_query(text: str, context: Dict[str,Any]) -> str:
    # mock account data: in real app fetch from backend
    fake_balance = "₹199.50"
    return f"Your current prepaid balance is {fake_balance}. Would you like to recharge now?"

def handle_symptom_check(text: str, context: Dict[str,Any]) -> str:
    # extremely simple triage: NEVER a replacement for professional advice
    if re.search(r"\b(fever|temperature)\b", text.lower()):
        return ("I see you mentioned fever. If temperature > 38°C or you have breathing difficulty, "
                "seek urgent care. For mild fever, rest, fluids and paracetamol are common. "
                "Do you have other symptoms?")
    if re.search(r"\b(chest pain|shortness of breath|severe|faint)\b", text.lower()):
        return ("These symptoms can be serious. If you are in immediate danger, please call emergency services now.")
    return ("Tell me more about your symptoms (how long, severity). I can help suggest next steps or book a tele-appointment.")

def handle_book_appointment(text: str, context: Dict[str,Any]) -> str:
    # example: in real app, query calendars and providers
    return ("I can help book an appointment. Which date/time and specialty do you prefer? "
            "Example: 'GP tomorrow morning' or 'Dermatology Nov 6 3pm'.")

def handle_greeting(text: str, context: Dict[str,Any]) -> str:
    return "Hello! I can help with mobile network support, account queries, or basic health triage. How can I help today?"

def handle_thanks(text: str, context: Dict[str,Any]) -> str:
    return "You're welcome — anything else I can help with?"

def handle_fallback(text: str, context: Dict[str,Any]) -> str:
    return ("Sorry, I didn't quite get that. Could you rephrase? "
            "You can ask about 'network issue', 'check my balance', or 'I have a fever'.")

INTENT_HANDLERS = {
    "network_issue": handle_network_issue,
    "account_query": handle_account_query,
    "symptom_check": handle_symptom_check,
    "book_appointment": handle_book_appointment,
    "greeting": handle_greeting,
    "thanks": handle_thanks,
    "fallback": handle_fallback,
}

# central respond function
def respond(message: str, session_id: str, context: Dict[str,Any]=None) -> Dict[str,Any]:
    if context is None:
        context = {}
    log_message(session_id, "user", message)
    intent = detect_intent(message)
    handler = INTENT_HANDLERS.get(intent["intent"], handle_fallback)
    reply = handler(message, context)
    log_message(session_id, "bot", reply)
    return {
        "reply": reply,
        "intent": intent,
        "timestamp": datetime.utcnow().isoformat()
    }

# --- REST endpoint for simple clients --- #
@app.post("/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", "guest")
    res = respond(message, session_id)
    return JSONResponse(content=res)

# --- WebSocket manager --- #
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)

    async def send_personal_message(self, message: str, session_id: str):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    try:
        await manager.send_personal_message(json.dumps({
            "reply": f"Connected to SimpleRealtimeChatbot as {session_id}. Say hi!"
        }), session_id)
        while True:
            data = await websocket.receive_text()
            # data expected to be plain text or JSON with {"message": "..."}
            try:
                payload = json.loads(data)
                message = payload.get("message", "")
            except Exception:
                message = data
            result = respond(message, session_id)
            # respond with a JSON payload
            await manager.send_personal_message(json.dumps(result), session_id)
    except WebSocketDisconnect:
        manager.disconnect(session_id)

# lightweight health check
@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
