"""
Iron Lady WATI Analytics - Complete Backend with Ticket System
FastAPI server with WATI webhook receiver, ticket management, and counsellor reply system

Author: Iron Lady Tech Team
Version: 7.0.0 - Final Production Ready
"""

import json
import re
import os
import requests
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ============================================
# LOAD ENVIRONMENT VARIABLES
# ============================================

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================
# CONFIGURATION
# ============================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/wati_analytics")
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

WATI_API_URL = os.getenv("WATI_SERVER", "https://live-server-113236.wati.io")
WATI_API_TOKEN = os.getenv("WATI_API_TOKEN", "")
WATI_TIMEOUT = 15

# ============================================
# DUPLICATE PREVENTION CACHE
# ============================================

PROCESSED_MESSAGE_IDS = set()
LAST_SENT_MESSAGES = {}  # phone -> {hash, time}

def is_duplicate_webhook(message_id: str) -> bool:
    """Check if webhook already processed"""
    if not message_id:
        return False
    if message_id in PROCESSED_MESSAGE_IDS:
        return True
    # Keep cache size manageable
    if len(PROCESSED_MESSAGE_IDS) > 5000:
        PROCESSED_MESSAGE_IDS.clear()
    PROCESSED_MESSAGE_IDS.add(message_id)
    return False

def can_send_message(phone: str, message: str) -> bool:
    """Check if we can send this message (prevent duplicates within 60 seconds)"""
    msg_hash = hashlib.md5(message.encode()).hexdigest()
    now = datetime.utcnow()
    
    if phone in LAST_SENT_MESSAGES:
        last = LAST_SENT_MESSAGES[phone]
        if last["hash"] == msg_hash:
            time_diff = (now - last["time"]).total_seconds()
            if time_diff < 60:
                return False
    
    LAST_SENT_MESSAGES[phone] = {"hash": msg_hash, "time": now}
    
    # Clean old entries
    if len(LAST_SENT_MESSAGES) > 1000:
        LAST_SENT_MESSAGES.clear()
    
    return True

# ============================================
# DATABASE SETUP
# ============================================

engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================
# TIMEZONE HELPER
# ============================================

def convert_to_ist(utc_dt):
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC"))
    return utc_dt.astimezone(ZoneInfo("Asia/Kolkata")).isoformat()

# ============================================
# DATABASE MODELS
# ============================================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True)
    participation_level = Column(String(50), default="Unknown")
    enrolled_program = Column(String(100), nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_interaction = Column(DateTime, default=datetime.utcnow)
    has_active_ticket = Column(Boolean, default=False)
    awaiting_ticket_type = Column(String(30), nullable=True)
    
    course_interests = relationship("CourseInterest", back_populates="user", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")


class Ticket(Base):
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(20), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(20), default="query")
    initial_message = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    last_user_message_at = Column(DateTime, default=datetime.utcnow)
    last_counsellor_reply_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(100), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    direction = Column(String(20), nullable=False)
    message_type = Column(String(20), default="text")
    message_text = Column(Text, nullable=True)
    media_url = Column(String(500), nullable=True)
    media_filename = Column(String(200), nullable=True)
    wati_message_id = Column(String(100), nullable=True, index=True)
    delivery_status = Column(String(20), default="sent")
    sent_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    
    ticket = relationship("Ticket", back_populates="messages")


class TicketCounter(Base):
    __tablename__ = "ticket_counter"
    
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, unique=True)
    last_number = Column(Integer, default=0)


class CourseInterest(Base):
    __tablename__ = "course_interests"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_name = Column(String(50), nullable=False)
    click_count = Column(Integer, default=1)
    first_clicked = Column(DateTime, default=datetime.utcnow)
    last_clicked = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="course_interests")


class Feedback(Base):
    __tablename__ = "feedbacks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    feedback_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="feedbacks")


class BroadcastMessage(Base):
    __tablename__ = "broadcast_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), nullable=False, index=True)
    recipient_name = Column(String(100), nullable=True)
    message_text = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")
    media_url = Column(String(500), nullable=True)
    caption = Column(Text, nullable=True)
    status = Column(String(20), default="sent", index=True)
    wati_message_id = Column(String(100), unique=True, nullable=True, index=True)
    failure_reason = Column(String(500), nullable=True)
    failed_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    manually_sent = Column(Boolean, default=False)
    manually_sent_at = Column(DateTime, nullable=True)
    manually_sent_by = Column(String(100), nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookLog(Base):
    __tablename__ = "webhook_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50))
    phone_number = Column(String(20), nullable=True)
    message_id = Column(String(100), nullable=True, index=True)
    is_outgoing = Column(Boolean, default=False)
    raw_data = Column(Text)
    processed = Column(Boolean, default=False)
    action_taken = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================
# DATABASE INITIALIZATION
# ============================================

def init_database():
    from sqlalchemy import inspect, text
    
    print("🔄 Initializing database...")
    Base.metadata.create_all(bind=engine)
    
    column_updates = [
        ("users", "has_active_ticket", "BOOLEAN DEFAULT FALSE"),
        ("users", "enrolled_program", "VARCHAR(100)"),
        ("users", "participation_level", "VARCHAR(50) DEFAULT 'Unknown'"),
        ("users", "awaiting_ticket_type", "VARCHAR(30)"),
        ("webhook_logs", "message_id", "VARCHAR(100)"),
    ]
    
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        with engine.connect() as conn:
            for table, column, definition in column_updates:
                if table in existing_tables:
                    existing_columns = [c['name'] for c in inspector.get_columns(table)]
                    if column not in existing_columns:
                        try:
                            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"))
                        except Exception:
                            pass
            conn.commit()
        print("✅ Database ready!")
    except Exception as e:
        print(f"⚠️ Database init warning: {e}")


init_database()

# ============================================
# FASTAPI APP
# ============================================

app = FastAPI(
    title="Iron Lady WATI Analytics API",
    description="Complete analytics backend with ticket system",
    version="7.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# DATABASE DEPENDENCY
# ============================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================
# PYDANTIC MODELS
# ============================================

class TicketReplyRequest(BaseModel):
    message: str
    counsellor_name: Optional[str] = "Counsellor"

class TicketStatusUpdateRequest(BaseModel):
    status: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None

# ============================================
# WATI API FUNCTIONS
# ============================================

def send_wati_message(phone_number: str, message: str) -> dict:
    """Send a text message via WATI API"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    # Check for duplicate
    if not can_send_message(phone_number, message):
        print(f"⚠️ Skipping duplicate message to {phone_number}")
        return {"success": True, "skipped": True}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/sendSessionMessage/{phone}?messageText={requests.utils.quote(message)}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        
        # Check for success - multiple possible indicators
        if response.status_code == 200:
            if result.get("result") == True:
                return {"success": True, "message_id": result.get("messageId"), "response": result}
            if result.get("whatsappMessageId"):
                return {"success": True, "message_id": result.get("whatsappMessageId"), "response": result}
            if result.get("statusString") == "SENT":
                return {"success": True, "message_id": result.get("whatsappMessageId") or result.get("localMessageId"), "response": result}
        
        return {"success": False, "error": result.get("message") or str(result), "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_wati_interactive_buttons(phone_number: str, body_text: str, buttons: list) -> dict:
    """Send interactive buttons via WATI API"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/sendInteractiveButtonsMessage?whatsappNumber={phone}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    payload = {"body": body_text, "buttons": [{"text": btn["text"]} for btn in buttons]}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=WATI_TIMEOUT)
        result = response.json()
        
        print(f"📤 WATI Response Status: {response.status_code}")
        
        if response.status_code == 200 and isinstance(result, dict):
            
            # WATI Response Format: {"ok": true, "errors": null, "message": {...}}
            # The actual message data is INSIDE the "message" key
            
            ok_status = result.get("ok")
            message_data = result.get("message")
            
            # Check if ok is True - this is the primary success indicator
            if ok_status == True:
                # Extract message ID from nested message object
                msg_id = None
                if isinstance(message_data, dict):
                    msg_id = message_data.get("whatsappMessageId") or message_data.get("localMessageId") or message_data.get("id")
                
                print(f"✅ Message sent successfully: {msg_id}")
                return {"success": True, "message_id": msg_id, "response": result}
            
            # Fallback: check top-level fields (older API format)
            wamid = result.get("whatsappMessageId")
            status_str = result.get("statusString")
            result_bool = result.get("result")
            
            if wamid or status_str == "SENT" or result_bool == True:
                final_id = wamid or result.get("localMessageId") or result.get("messageId")
                print(f"✅ Message sent successfully: {final_id}")
                return {"success": True, "message_id": final_id, "response": result}
        
        # If we got here, something went wrong
        errors = result.get("errors") if isinstance(result, dict) else None
        error_msg = str(errors) if errors else "Unknown error"
        print(f"❌ WATI Error: {error_msg}")
        return {"success": False, "error": error_msg, "response": result}
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return {"success": False, "error": str(e)}


def send_wati_media(phone_number: str, media_url: str, caption: str = "") -> dict:
    """Send media via WATI API"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/sendSessionFile/{phone}"
    
    headers = {"Authorization": f"Bearer {WATI_API_TOKEN}", "Content-Type": "application/json"}
    
    try:
        response = requests.post(url, headers=headers, json={"url": media_url, "caption": caption}, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and (result.get("result") or result.get("whatsappMessageId")):
            return {"success": True, "message_id": result.get("whatsappMessageId") or result.get("messageId"), "response": result}
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def assign_to_operator(phone_number: str, operator_email: str = "Admin@iamironlady.com") -> dict:
    """Assign conversation to operator"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/assignOperator?whatsappNumber={phone}&operatorEmail={operator_email}"
    
    headers = {"Authorization": f"Bearer {WATI_API_TOKEN}", "Content-Type": "application/json-patch+json"}
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        return {"success": response.status_code == 200, "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def unassign_operator(phone_number: str) -> dict:
    """Unassign conversation from operator"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/unassignOperator?whatsappNumber={phone}"
    
    headers = {"Authorization": f"Bearer {WATI_API_TOKEN}", "Content-Type": "application/json-patch+json"}
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        return {"success": response.status_code == 200, "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_ticket_number(db: Session) -> str:
    current_year = datetime.utcnow().year
    counter = db.query(TicketCounter).filter(TicketCounter.year == current_year).first()
    
    if not counter:
        counter = TicketCounter(year=current_year, last_number=0)
        db.add(counter)
    
    counter.last_number += 1
    db.commit()
    return f"TKT-{current_year}-{counter.last_number:04d}"


def get_or_create_user(db: Session, phone_number: str, name: str = None) -> User:
    phone_number = phone_number.replace("+", "").replace(" ", "").strip()
    user = db.query(User).filter(User.phone_number == phone_number).first()
    
    if not user:
        user = User(phone_number=phone_number, name=name, participation_level="Unknown")
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.last_interaction = datetime.utcnow()
        if name and not user.name:
            user.name = name
        db.commit()
    return user


def get_active_ticket(db: Session, phone_number: str) -> Optional[Ticket]:
    phone_number = phone_number.replace("+", "").replace(" ", "").strip()
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if not user:
        return None
    
    return db.query(Ticket).filter(
        Ticket.user_id == user.id,
        Ticket.status.in_(["pending", "in_progress", "awaiting"])
    ).order_by(Ticket.created_at.desc()).first()


# ============================================
# MESSAGE MATCHING
# ============================================

QUERY_BUTTONS = ["i have a query", "have a query", "query"]
CONCERN_BUTTONS = ["raise a concern", "have a concern", "concern"]

# EXACT button texts from WATI
SATISFACTION_YES = ["yes, resolved", "yes,resolved"]
SATISFACTION_NO = ["need more help", "needmorehelp"]

# Chatbot flow messages - DO NOT respond to these
CHATBOT_MESSAGES = [
    "new to platform", "enrolled participant", "more options",
    "please choose your participation", "ask a question here",
    "lep", "100bm", "mbw", "masterclass", "know more", "feedback"
]

IGNORE_MESSAGES = [
    "hi", "hello", "hey", "ok", "okay", "thanks", "thank you",
    "bye", "good morning", "good night", "hmm", "yes", "no"
]


def get_message_type(message: str) -> str:
    """Determine the type of message"""
    msg = message.lower().strip()
    
    # Check satisfaction buttons FIRST (exact match)
    if msg in SATISFACTION_YES or "yes, resolved" in msg:
        return "satisfaction_yes"
    
    if msg in SATISFACTION_NO or "need more help" in msg:
        return "satisfaction_no"
    
    # Check query/concern buttons
    for btn in QUERY_BUTTONS:
        if btn in msg:
            return "query_button"
    
    for btn in CONCERN_BUTTONS:
        if btn in msg:
            return "concern_button"
    
    # Check chatbot messages
    for cb in CHATBOT_MESSAGES:
        if cb in msg:
            return "chatbot_flow"
    
    # Check ignore messages
    if msg in IGNORE_MESSAGES or len(msg) < 3:
        return "ignore"
    
    return "regular"


def extract_email(text: str) -> Optional[str]:
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, text)
    return match.group() if match else None


# ============================================
# WEBHOOK ENDPOINT
# ============================================

@app.post("/webhook/wati")
async def wati_webhook(data: dict, db: Session = Depends(get_db)):
    """WATI Webhook - v7.0.0 Final"""
    
    # Extract data
    wa_number = data.get("waId") or data.get("waNumber") or ""
    sender_name = data.get("senderName", "").replace("~", "").strip() or None
    event_type = data.get("eventType", "")
    message_text = data.get("text", "") or ""
    message_id = data.get("id") or data.get("messageId") or ""
    
    # Extract button text
    button_text = data.get("buttonText") or data.get("listResponseTitle") or ""
    
    if not button_text:
        for key in ["button", "interactive", "listReply", "buttonReply"]:
            obj = data.get(key)
            if isinstance(obj, dict):
                button_text = obj.get("text") or obj.get("title") or ""
                if not button_text and key == "interactive":
                    br = obj.get("button_reply")
                    if isinstance(br, dict):
                        button_text = br.get("title", "")
                if button_text:
                    break
    
    if button_text:
        message_text = button_text
    
    # Check if outgoing
    is_outgoing = (
        data.get("owner") == True or 
        data.get("isFromMe") == True or
        data.get("fromMe") == True or
        str(data.get("owner", "")).lower() == "true" or
        str(data.get("isOwner", "")).lower() == "true" or
        event_type in ["sessionMessageSent", "session_message_sent", "message_sent"]
    )
    
    # ========================================
    # DUPLICATE CHECK
    # ========================================
    if message_id and is_duplicate_webhook(message_id):
        return {"status": "duplicate"}
    
    # Log webhook
    log = WebhookLog(
        event_type=event_type,
        phone_number=wa_number,
        message_id=message_id,
        is_outgoing=is_outgoing,
        raw_data=json.dumps(data)[:5000],
        processed=False
    )
    db.add(log)
    db.commit()
    
    try:
        # ========================================
        # IGNORE: Status updates
        # ========================================
        if event_type in ["sentMessageDELIVERED", "sentMessageREAD", "delivered", "read", "failed"]:
            log.action_taken = "status_update"
            log.processed = True
            db.commit()
            return {"status": "ok"}
        
        # ========================================
        # IGNORE: No phone or outgoing
        # ========================================
        if not wa_number:
            log.action_taken = "no_phone"
            log.processed = True
            db.commit()
            return {"status": "ignored"}
        
        wa_number = wa_number.replace("+", "").replace(" ", "")
        
        if is_outgoing:
            log.action_taken = "outgoing"
            log.processed = True
            db.commit()
            return {"status": "ignored"}
        
        if not message_text:
            log.action_taken = "no_text"
            log.processed = True
            db.commit()
            return {"status": "ignored"}
        
        # ========================================
        # PROCESS INCOMING MESSAGE
        # ========================================
        user = get_or_create_user(db, wa_number, sender_name)
        active_ticket = get_active_ticket(db, wa_number)
        msg_type = get_message_type(message_text)
        
        print(f"📨 [{wa_number}] Type: {msg_type} | Text: {message_text[:50]}...")
        
        # ----------------------------------------
        # CHATBOT FLOW - Don't respond
        # ----------------------------------------
        if msg_type == "chatbot_flow":
            log.action_taken = "chatbot_flow"
            log.processed = True
            db.commit()
            return {"status": "chatbot"}
        
        # ----------------------------------------
        # IGNORE casual messages (when no ticket)
        # ----------------------------------------
        if msg_type == "ignore" and not active_ticket:
            log.action_taken = "ignored"
            log.processed = True
            db.commit()
            return {"status": "ignored"}
        
        # ----------------------------------------
        # QUERY BUTTON
        # ----------------------------------------
        if msg_type == "query_button":
            user.awaiting_ticket_type = "query"
            db.commit()
            log.action_taken = "awaiting_query"
            log.processed = True
            db.commit()
            return {"status": "awaiting_query"}
        
        # ----------------------------------------
        # CONCERN BUTTON
        # ----------------------------------------
        if msg_type == "concern_button":
            user.awaiting_ticket_type = "concern"
            db.commit()
            log.action_taken = "awaiting_concern"
            log.processed = True
            db.commit()
            return {"status": "awaiting_concern"}
        
        # ----------------------------------------
        # CREATE TICKET (user was awaiting)
        # ----------------------------------------
        if user.awaiting_ticket_type in ["query", "concern"]:
            category = user.awaiting_ticket_type
            ticket_number = generate_ticket_number(db)
            
            ticket = Ticket(
                ticket_number=ticket_number,
                user_id=user.id,
                category=category,
                initial_message=message_text,
                status="pending",
                last_user_message_at=datetime.utcnow()
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            
            db.add(TicketMessage(
                ticket_id=ticket.id,
                direction="incoming",
                message_type="text",
                message_text=message_text,
                wati_message_id=message_id,
                sent_by=sender_name
            ))
            
            user.awaiting_ticket_type = None
            user.has_active_ticket = True
            db.commit()
            
            # Assign to operator
            assign_to_operator(wa_number)
            
            # Send confirmation
            msg = f"✅ Your ticket {ticket_number} has been created for this {category}.\n\nOur counsellor will reach out to you within the next 24 hours.\n\nThank you for your patience!"
            send_wati_message(wa_number, msg)
            
            log.action_taken = f"created_{ticket_number}"
            log.processed = True
            db.commit()
            return {"status": "ticket_created", "ticket": ticket_number}
        
        # ----------------------------------------
        # ACTIVE TICKET: Satisfaction YES
        # ----------------------------------------
        if active_ticket and msg_type == "satisfaction_yes":
            active_ticket.status = "resolved"
            active_ticket.resolved_at = datetime.utcnow()
            user.has_active_ticket = False
            db.commit()
            
            send_wati_message(wa_number, f"Thank you for confirming! Your ticket {active_ticket.ticket_number} has been resolved.\n\nWe're glad we could help!")
            unassign_operator(wa_number)
            
            log.action_taken = f"resolved_{active_ticket.ticket_number}"
            log.processed = True
            db.commit()
            return {"status": "resolved"}
        
        # ----------------------------------------
        # ACTIVE TICKET: Satisfaction NO
        # ----------------------------------------
        if active_ticket and msg_type == "satisfaction_no":
            # Only respond if not already awaiting
            if active_ticket.status != "awaiting":
                active_ticket.status = "awaiting"
                active_ticket.last_user_message_at = datetime.utcnow()
                db.commit()
                
                db.add(TicketMessage(
                    ticket_id=active_ticket.id,
                    direction="incoming",
                    message_type="text",
                    message_text="[User needs more help]",
                    wati_message_id=message_id
                ))
                db.commit()
                
                send_wati_message(wa_number, "Please share what additional help you need:")
            
            log.action_taken = f"need_help_{active_ticket.ticket_number}"
            log.processed = True
            db.commit()
            return {"status": "need_more_help"}
        
        # ----------------------------------------
        # ACTIVE TICKET: Follow-up message
        # ----------------------------------------
        if active_ticket:
            db.add(TicketMessage(
                ticket_id=active_ticket.id,
                direction="incoming",
                message_type="text",
                message_text=message_text,
                wati_message_id=message_id,
                sent_by=sender_name
            ))
            active_ticket.last_user_message_at = datetime.utcnow()
            
            # Only send confirmation if ticket was in "awaiting" status
            if active_ticket.status == "awaiting":
                active_ticket.status = "pending"
                db.commit()
                send_wati_message(wa_number, f"Your ticket {active_ticket.ticket_number} is still in progress. Our counsellor will reach you within 24 hours. 🙏")
                log.action_taken = f"followup_{active_ticket.ticket_number}"
            else:
                db.commit()
                log.action_taken = f"silent_{active_ticket.ticket_number}"
            
            log.processed = True
            db.commit()
            return {"status": "followup"}
        
        # ----------------------------------------
        # NO TICKET: Check for email
        # ----------------------------------------
        email = extract_email(message_text)
        if email:
            user.email = email
            db.commit()
            log.action_taken = "email_captured"
            log.processed = True
            db.commit()
            return {"status": "email_captured"}
        
        # ----------------------------------------
        # DEFAULT: Just log
        # ----------------------------------------
        log.action_taken = "logged"
        log.processed = True
        db.commit()
        return {"status": "logged"}
    
    except Exception as e:
        log.action_taken = f"error:{str(e)[:50]}"
        log.processed = False
        db.commit()
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}


# ============================================
# ROOT & HEALTH
# ============================================

@app.get("/")
async def root():
    return {"name": "Iron Lady WATI Analytics", "version": "7.0.0", "status": "running"}


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        return {
            "status": "healthy",
            "database": "connected",
            "users": db.query(User).count(),
            "tickets": db.query(Ticket).count(),
            "pending": db.query(Ticket).filter(Ticket.status == "pending").count(),
            "wati": bool(WATI_API_TOKEN),
            "version": "7.0.0"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ============================================
# TICKET ENDPOINTS
# ============================================

@app.get("/api/tickets")
async def get_tickets(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(Ticket).join(User)
    if status:
        query = query.filter(Ticket.status == status)
    
    tickets = query.order_by(Ticket.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for t in tickets:
        last_msg = t.last_user_message_at or t.created_at
        hours_left = max(0, 24 - (datetime.utcnow() - last_msg).total_seconds() / 3600)
        msg_count = db.query(TicketMessage).filter(TicketMessage.ticket_id == t.id).count()
        
        result.append({
            "id": t.id,
            "ticket_number": t.ticket_number,
            "user_name": t.user.name,
            "user_phone": t.user.phone_number,
            "category": t.category,
            "initial_message": t.initial_message,
            "status": t.status,
            "message_count": msg_count,
            "is_24hr_active": hours_left > 0,
            "hours_remaining": round(hours_left, 1),
            "created_at": convert_to_ist(t.created_at),
            "last_user_message_at": convert_to_ist(t.last_user_message_at),
            "last_counsellor_reply_at": convert_to_ist(t.last_counsellor_reply_at)
        })
    
    return {
        "tickets": result,
        "stats": {
            "total": db.query(Ticket).count(),
            "pending": db.query(Ticket).filter(Ticket.status == "pending").count(),
            "in_progress": db.query(Ticket).filter(Ticket.status == "in_progress").count(),
            "resolved": db.query(Ticket).filter(Ticket.status == "resolved").count()
        }
    }


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    messages = db.query(TicketMessage).filter(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at.asc()).all()
    
    last_msg = ticket.last_user_message_at or ticket.created_at
    hours_left = max(0, 24 - (datetime.utcnow() - last_msg).total_seconds() / 3600)
    
    return {
        "ticket": {
            "id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "category": ticket.category,
            "initial_message": ticket.initial_message,
            "status": ticket.status,
            "is_24hr_active": hours_left > 0,
            "hours_remaining": round(hours_left, 1),
            "created_at": convert_to_ist(ticket.created_at),
            "resolved_at": convert_to_ist(ticket.resolved_at)
        },
        "user": {
            "id": ticket.user.id,
            "name": ticket.user.name,
            "phone_number": ticket.user.phone_number,
            "email": ticket.user.email
        },
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "message_text": m.message_text,
                "sent_by": m.sent_by,
                "delivery_status": m.delivery_status,
                "created_at": convert_to_ist(m.created_at)
            }
            for m in messages
        ]
    }


@app.post("/api/tickets/{ticket_id}/reply")
async def send_reply(ticket_id: int, reply: TicketReplyRequest, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status == "resolved":
        raise HTTPException(status_code=400, detail="Ticket already resolved")
    
    last_msg = ticket.last_user_message_at or ticket.created_at
    hours_since = (datetime.utcnow() - last_msg).total_seconds() / 3600
    
    if hours_since > 24:
        raise HTTPException(status_code=400, detail="24-hour window expired")
    
    phone = ticket.user.phone_number
    
    # Send with satisfaction buttons
    full_msg = f"{reply.message}\n\n───────────────────\nAre you satisfied with this response?"
    buttons = [{"text": "Yes, Resolved"}, {"text": "Need More Help"}]
    
    result = send_wati_interactive_buttons(phone, full_msg, buttons)
    
    # Check success properly
    if result.get("success") or result.get("message_id"):
        db.add(TicketMessage(
            ticket_id=ticket.id,
            direction="outgoing",
            message_type="text",
            message_text=reply.message,
            sent_by=reply.counsellor_name,
            wati_message_id=result.get("message_id"),
            delivery_status="sent"
        ))
        
        ticket.status = "in_progress"
        ticket.last_counsellor_reply_at = datetime.utcnow()
        db.commit()
        
        return {"success": True, "message": "Reply sent", "message_id": result.get("message_id")}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send: {result.get('error')}")


@app.patch("/api/tickets/{ticket_id}/status")
async def update_status(ticket_id: int, update: TicketStatusUpdateRequest, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.status = update.status
    
    if update.status == "resolved":
        ticket.resolved_at = datetime.utcnow()
        ticket.user.has_active_ticket = False
        unassign_operator(ticket.user.phone_number)
    
    if update.resolved_by:
        ticket.resolved_by = update.resolved_by
    
    db.commit()
    return {"success": True, "status": update.status}


# ============================================
# USER ENDPOINTS
# ============================================

@app.get("/api/users")
async def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.last_interaction.desc()).offset(skip).limit(limit).all()
    
    return {
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "phone_number": u.phone_number,
                "email": u.email,
                "participation_level": u.participation_level,
                "has_active_ticket": u.has_active_ticket,
                "last_interaction": convert_to_ist(u.last_interaction)
            }
            for u in users
        ],
        "total": db.query(User).count()
    }


# ============================================
# ANALYTICS
# ============================================

@app.get("/api/analytics/summary")
async def analytics(db: Session = Depends(get_db)):
    return {
        "users": {"total": db.query(User).count()},
        "tickets": {
            "total": db.query(Ticket).count(),
            "pending": db.query(Ticket).filter(Ticket.status == "pending").count(),
            "in_progress": db.query(Ticket).filter(Ticket.status == "in_progress").count(),
            "resolved": db.query(Ticket).filter(Ticket.status == "resolved").count()
        }
    }


# ============================================
# WEBHOOK LOGS
# ============================================

@app.get("/api/webhook-logs")
async def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(WebhookLog).order_by(WebhookLog.created_at.desc()).limit(limit).all()
    return {
        "logs": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "phone_number": l.phone_number,
                "message_id": l.message_id,
                "is_outgoing": l.is_outgoing,
                "action_taken": l.action_taken,
                "created_at": convert_to_ist(l.created_at)
            }
            for l in logs
        ]
    }


# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    import uvicorn
    print()
    print("=" * 50)
    print("🚀 Iron Lady WATI Analytics API v7.0.0")
    print("=" * 50)
    print(f"📍 http://{API_HOST}:{API_PORT}")
    print(f"📚 Docs: http://{API_HOST}:{API_PORT}/docs")
    print(f"🔑 WATI: {'✅' if WATI_API_TOKEN else '❌'}")
    print()
    uvicorn.run(app, host=API_HOST, port=API_PORT)
