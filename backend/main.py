"""
Iron Lady WATI Analytics - Complete Backend with Ticket System
FastAPI server with WATI webhook receiver, ticket management, and counsellor reply system

Author: Iron Lady Tech Team
Version: 6.1.0 - Optimized for Production (AWS Ready)
"""

import json
import re
import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List
from enum import Enum

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text, func, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
import enum

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

# WATI Configuration
WATI_API_URL = os.getenv("WATI_SERVER", "https://live-server-113236.wati.io")
WATI_API_TOKEN = os.getenv("WATI_API_TOKEN", "")

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
    """Convert UTC datetime to IST (Indian Standard Time)"""
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC"))
    return utc_dt.astimezone(ZoneInfo("Asia/Kolkata")).isoformat()

def get_ist_now():
    """Get current time in IST"""
    return datetime.now(ZoneInfo("Asia/Kolkata"))

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
    wati_message_id = Column(String(100), nullable=True)
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
    is_outgoing = Column(Boolean, default=False)
    raw_data = Column(Text)
    processed = Column(Boolean, default=False)
    action_taken = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================
# DATABASE INITIALIZATION
# ============================================

def init_database():
    """Initialize database safely"""
    from sqlalchemy import inspect, text
    
    print("🔄 Initializing database...")
    Base.metadata.create_all(bind=engine)
    
    column_updates = [
        ("users", "has_active_ticket", "BOOLEAN DEFAULT FALSE"),
        ("users", "enrolled_program", "VARCHAR(100)"),
        ("users", "participation_level", "VARCHAR(50) DEFAULT 'Unknown'"),
        ("users", "awaiting_ticket_type", "VARCHAR(30)"),
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
    description="Complete analytics backend with ticket system and counsellor replies",
    version="6.1.0",
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

class BroadcastMarkResentRequest(BaseModel):
    manually_sent_by: Optional[str] = "Dashboard User"

# ============================================
# WATI API HELPER FUNCTIONS (Optimized - reduced timeouts)
# ============================================

WATI_TIMEOUT = 10  # Reduced from 30 seconds

def send_wati_message(phone_number: str, message: str) -> dict:
    """Send a text message via WATI API"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/sendSessionMessage/{phone}?messageText={requests.utils.quote(message)}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and result.get("result"):
            return {
                "success": True,
                "message_id": result.get("messageId") or result.get("id"),
                "response": result
            }
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
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
    
    payload = {
        "body": body_text,
        "buttons": [{"text": btn["text"]} for btn in buttons]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=WATI_TIMEOUT)
        result = response.json()
        
        is_success = (
            response.status_code == 200 and 
            (result.get("result") == True or 
             result.get("statusString") == "SENT" or
             result.get("whatsappMessageId") is not None)
        )
        
        if is_success:
            return {
                "success": True,
                "message_id": result.get("messageId") or result.get("whatsappMessageId") or result.get("id"),
                "response": result
            }
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_wati_media(phone_number: str, media_url: str, caption: str = "", media_type: str = "image") -> dict:
    """Send media via WATI API"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/sendSessionFile/{phone}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json={"url": media_url, "caption": caption}, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and result.get("result"):
            return {"success": True, "message_id": result.get("messageId") or result.get("id"), "response": result}
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def assign_to_operator(phone_number: str, operator_email: str = "Admin@iamironlady.com") -> dict:
    """Assign conversation to operator"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/assignOperator?whatsappNumber={phone}&operatorEmail={operator_email}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and result.get("result"):
            return {"success": True, "response": result}
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def unassign_operator(phone_number: str) -> dict:
    """Unassign conversation from operator"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/unassignOperator?whatsappNumber={phone}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and result.get("result"):
            return {"success": True, "response": result}
        return {"success": False, "error": result.get("message") or "Unknown error", "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# TICKET HELPER FUNCTIONS
# ============================================

def generate_ticket_number(db: Session) -> str:
    """Generate unique ticket number"""
    current_year = datetime.utcnow().year
    counter = db.query(TicketCounter).filter(TicketCounter.year == current_year).first()
    
    if not counter:
        counter = TicketCounter(year=current_year, last_number=0)
        db.add(counter)
    
    counter.last_number += 1
    db.commit()
    return f"TKT-{current_year}-{counter.last_number:04d}"


def get_or_create_user(db: Session, phone_number: str, name: str = None, email: str = None) -> User:
    """Get or create user"""
    phone_number = phone_number.replace("+", "").replace(" ", "").strip()
    user = db.query(User).filter(User.phone_number == phone_number).first()
    
    if not user:
        user = User(phone_number=phone_number, name=name, email=email, participation_level="Unknown")
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.last_interaction = datetime.utcnow()
        if name and not user.name:
            user.name = name
        if email and not user.email:
            user.email = email
        db.commit()
    return user


def get_active_ticket_for_user(db: Session, phone_number: str) -> Optional[Ticket]:
    """Get active ticket for user"""
    phone_number = phone_number.replace("+", "").replace(" ", "").strip()
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if not user:
        return None
    
    return db.query(Ticket).filter(
        Ticket.user_id == user.id,
        Ticket.status.in_(["pending", "in_progress", "awaiting"])
    ).order_by(Ticket.created_at.desc()).first()


def update_course_interest(db: Session, user_id: int, course_name: str):
    """Update course interest"""
    interest = db.query(CourseInterest).filter(
        CourseInterest.user_id == user_id,
        CourseInterest.course_name == course_name
    ).first()
    
    if interest:
        interest.click_count += 1
        interest.last_clicked = datetime.utcnow()
    else:
        db.add(CourseInterest(user_id=user_id, course_name=course_name))
    db.commit()


def add_enrolled_program(user: User, program: str):
    """Add enrolled program"""
    if not user.enrolled_program:
        user.enrolled_program = program
    elif program not in user.enrolled_program:
        user.enrolled_program = f"{user.enrolled_program},{program}"


# ============================================
# MESSAGE HELPERS
# ============================================

QUERY_BUTTONS = ["i have a query", "have a query", "query", "have query"]
CONCERN_BUTTONS = ["raise a concern", "have a concern", "concern", "raise concern"]

SATISFACTION_YES_RESPONSES = {"yes, resolved", "yes,resolved", "yes resolved", "resolved", "yes"}
SATISFACTION_NO_RESPONSES = {"need more help", "needmorehelp", "need help", "more help", "no"}

CHATBOT_BUTTONS = [
    "new to platform", "enrolled participant", "more options",
    "lep", "100bm", "mbw", "masterclass", "leadership essentials",
    "100 board members", "master of business warfare", "know more",
    "ask a question", "feedback"
]

IGNORE_MESSAGES = {
    "hi", "hello", "hey", "hii", "hiii", "helloo", "hellooo",
    "good morning", "good night", "good evening", "gm", "gn",
    "morning", "night", "evening", "bye", "byee", "goodbye",
    "thanks", "thank you", "thankyou", "thnx", "thx", "ty",
    "ok", "okay", "k", "oky", "yes", "no", "ya", "yep", "nope", "yup",
    "hmm", "hm", "mm", "cool", "nice", "great", "awesome", "sure",
    "alright", "fine", "good", "bad", "np"
}


def should_ignore_message(message: str) -> bool:
    message_lower = message.lower().strip()
    return message_lower in IGNORE_MESSAGES or len(message.strip()) < 3


def extract_email(text: str) -> Optional[str]:
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, text)
    return match.group() if match else None


def is_satisfaction_response(message: str) -> Optional[bool]:
    """Check satisfaction response"""
    message_lower = message.lower().strip()
    
    if message_lower in SATISFACTION_YES_RESPONSES:
        return True
    elif message_lower in SATISFACTION_NO_RESPONSES:
        return False
    
    # Partial match
    for yes_response in SATISFACTION_YES_RESPONSES:
        if yes_response in message_lower or message_lower in yes_response:
            return True
    
    for no_response in SATISFACTION_NO_RESPONSES:
        if no_response in message_lower or message_lower in no_response:
            return False
    
    return None


# ============================================
# WEBHOOK ENDPOINT - OPTIMIZED
# ============================================

@app.post("/webhook/wati")
async def wati_webhook(data: dict, db: Session = Depends(get_db)):
    """WATI Webhook Receiver - v6.1.0 Optimized"""
    
    wa_number = data.get("waId") or data.get("waNumber") or ""
    sender_name = data.get("senderName", "").replace("~", "").strip() or None
    event_type = data.get("eventType", "")
    message_text = data.get("text", "") or ""
    message_id = data.get("id") or data.get("messageId")
    
    # Extract button text from various WATI formats
    button_text = data.get("buttonText") or data.get("listResponseTitle") or ""
    
    if not button_text:
        button_obj = data.get("button")
        if isinstance(button_obj, dict):
            button_text = button_obj.get("text", "")
    
    if not button_text:
        interactive_obj = data.get("interactive")
        if isinstance(interactive_obj, dict):
            button_reply = interactive_obj.get("button_reply")
            if isinstance(button_reply, dict):
                button_text = button_reply.get("title", "")
    
    if not button_text:
        list_reply = data.get("listReply")
        if isinstance(list_reply, dict):
            button_text = list_reply.get("title", "")
    
    if not button_text:
        button_reply = data.get("buttonReply")
        if isinstance(button_reply, dict):
            button_text = button_reply.get("title", "")
    
    if button_text:
        message_text = button_text
    
    message_lower = message_text.lower().strip()
    
    is_outgoing = (
        data.get("owner", False) == True or 
        data.get("isFromMe", False) == True or
        data.get("fromMe", False) == True or
        str(data.get("owner", "")).lower() == "true" or
        event_type in ["sessionMessageSent", "session_message_sent", "message_sent"]
    )
    
    # Create webhook log
    log = WebhookLog(
        event_type=event_type,
        phone_number=wa_number,
        is_outgoing=is_outgoing,
        raw_data=json.dumps(data),
        processed=False,
        action_taken=None
    )
    db.add(log)
    db.commit()
    
    try:
        # Handle status updates
        if event_type in ["templateMessageFailed", "sentMessageDELIVERED", "sentMessageREAD", "sent", "delivered", "read", "failed"]:
            if message_id:
                ticket_msg = db.query(TicketMessage).filter(TicketMessage.wati_message_id == message_id).first()
                if ticket_msg:
                    if event_type in ["sentMessageDELIVERED", "delivered"]:
                        ticket_msg.delivery_status = "delivered"
                        ticket_msg.delivered_at = datetime.utcnow()
                    elif event_type in ["sentMessageREAD", "read"]:
                        ticket_msg.delivery_status = "read"
                        ticket_msg.read_at = datetime.utcnow()
                    elif event_type in ["templateMessageFailed", "failed"]:
                        ticket_msg.delivery_status = "failed"
                    db.commit()
                    log.action_taken = f"ticket_message_{event_type}"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": log.action_taken}
                
                broadcast = db.query(BroadcastMessage).filter(BroadcastMessage.wati_message_id == message_id).first()
                if broadcast:
                    if event_type in ["sentMessageDELIVERED", "delivered"]:
                        broadcast.status = "delivered"
                        broadcast.delivered_at = datetime.utcnow()
                    elif event_type in ["sentMessageREAD", "read"]:
                        broadcast.status = "read"
                        broadcast.read_at = datetime.utcnow()
                    elif event_type in ["templateMessageFailed", "failed"]:
                        broadcast.status = "failed"
                        broadcast.failed_at = datetime.utcnow()
                        broadcast.failure_reason = data.get("failedDetail") or data.get("errorMessage") or "Unknown"
                    db.commit()
                    log.action_taken = f"broadcast_{event_type}"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": log.action_taken}
        
        if not wa_number:
            log.action_taken = "ignored_no_phone"
            log.processed = True
            db.commit()
            return {"status": "ignored", "reason": "No phone number"}
        
        wa_number = wa_number.replace("+", "").replace(" ", "")
        
        # Handle outgoing messages
        if is_outgoing and message_text:
            user = get_or_create_user(db, wa_number, name=sender_name)
            
            if "thrilled to inform" in message_lower and "registration" in message_lower:
                user.participation_level = "Enrolled Participant"
                if "leadership essentials" in message_lower:
                    add_enrolled_program(user, "LEP")
                elif "100 board" in message_lower:
                    add_enrolled_program(user, "100BM")
                elif "business warfare" in message_lower or "mbw" in message_lower:
                    add_enrolled_program(user, "MBW")
                elif "masterclass" in message_lower:
                    add_enrolled_program(user, "Masterclass")
                db.commit()
            
            if "leadership essentials program enables you to master" in message_lower:
                update_course_interest(db, user.id, "LEP")
            elif "100 board members program enables you to focus" in message_lower:
                update_course_interest(db, user.id, "100BM")
            elif "master of business warfare focuses on winning" in message_lower:
                update_course_interest(db, user.id, "MBW")
            elif "iron lady leadership masterclass helps you" in message_lower:
                update_course_interest(db, user.id, "Masterclass")
            
            if "welcome to the iron lady platform" in message_lower:
                user.participation_level = "New to platform"
                db.commit()
            
            if "ask a question here" in message_lower:
                user.participation_level = "Enrolled Participant"
                db.commit()
            
            log.processed = True
            db.commit()
            return {"status": "processed", "action": "bot_message_logged"}
        
        # Handle incoming messages
        if not is_outgoing and message_text:
            user = get_or_create_user(db, wa_number, name=sender_name)
            active_ticket = get_active_ticket_for_user(db, wa_number)
            
            # Check Query/Concern buttons
            if any(btn in message_lower for btn in QUERY_BUTTONS):
                user.awaiting_ticket_type = "query"
                db.commit()
                log.action_taken = "set_awaiting_query"
                log.processed = True
                db.commit()
                return {"status": "awaiting_query"}
            
            if any(btn in message_lower for btn in CONCERN_BUTTONS):
                user.awaiting_ticket_type = "concern"
                db.commit()
                log.action_taken = "set_awaiting_concern"
                log.processed = True
                db.commit()
                return {"status": "awaiting_concern"}
            
            # Create ticket if awaiting
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
                    sent_by=sender_name
                ))
                
                user.awaiting_ticket_type = None
                user.has_active_ticket = True
                db.commit()
                
                # Assign to operator and send confirmation
                assign_to_operator(wa_number)
                send_wati_message(wa_number, f"✅ Your ticket {ticket_number} has been created for this {category}.\n\nOur counsellor will reach out to you within the next 24 hours.\n\nThank you for your patience! 🙏")
                
                log.action_taken = f"ticket_created_{ticket_number}"
                log.processed = True
                db.commit()
                return {"status": "ticket_created", "ticket_number": ticket_number, "category": category}
            
            # Handle active ticket responses
            if active_ticket:
                satisfaction = is_satisfaction_response(message_text)
                
                if satisfaction is True:
                    active_ticket.status = "resolved"
                    active_ticket.resolved_at = datetime.utcnow()
                    user.has_active_ticket = False
                    db.commit()
                    
                    send_wati_message(wa_number, f"Thank you for confirming! Your ticket {active_ticket.ticket_number} has been resolved.\n\nWe're glad we could help! 💪")
                    unassign_operator(wa_number)
                    
                    log.action_taken = f"ticket_resolved_{active_ticket.ticket_number}"
                    log.processed = True
                    db.commit()
                    return {"status": "ticket_resolved", "ticket_number": active_ticket.ticket_number}
                
                elif satisfaction is False:
                    db.add(TicketMessage(
                        ticket_id=active_ticket.id,
                        direction="incoming",
                        message_type="text",
                        message_text="[User requested more help]",
                        sent_by=sender_name
                    ))
                    active_ticket.last_user_message_at = datetime.utcnow()
                    active_ticket.status = "awaiting"
                    db.commit()
                    
                    send_wati_message(wa_number, "Please share what additional help you need:")
                    
                    log.action_taken = f"need_more_help_{active_ticket.ticket_number}"
                    log.processed = True
                    db.commit()
                    return {"status": "need_more_help"}
                
                # Chatbot button - ignore
                if any(btn in message_lower for btn in CHATBOT_BUTTONS):
                    log.action_taken = f"chatbot_button_ignored"
                    log.processed = True
                    db.commit()
                    return {"status": "chatbot_button_ignored"}
                
                # Follow-up message
                db.add(TicketMessage(
                    ticket_id=active_ticket.id,
                    direction="incoming",
                    message_type="text",
                    message_text=message_text,
                    sent_by=sender_name
                ))
                active_ticket.last_user_message_at = datetime.utcnow()
                
                if active_ticket.status == "awaiting":
                    active_ticket.status = "pending"
                    db.commit()
                    send_wati_message(wa_number, f"Your ticket {active_ticket.ticket_number} is still in progress. Our counsellor will reach you within 24 hours. 🙏")
                    log.action_taken = f"ticket_followup_confirmed_{active_ticket.ticket_number}"
                else:
                    db.commit()
                    log.action_taken = f"ticket_followup_silent_{active_ticket.ticket_number}"
                
                log.processed = True
                db.commit()
                return {"status": "followup_added", "ticket_number": active_ticket.ticket_number}
            
            # No ticket context
            email = extract_email(message_text)
            if email:
                user.email = email
                db.commit()
                log.action_taken = "email_captured"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "email_captured", "email": email}
            
            if should_ignore_message(message_text):
                log.action_taken = "casual_ignored"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "casual_ignored"}
            
            log.action_taken = "message_logged"
            log.processed = True
            db.commit()
            return {"status": "processed", "action": "message_logged"}
        
        log.action_taken = "logged"
        log.processed = True
        db.commit()
        return {"status": "processed", "action": "logged"}
    
    except Exception as e:
        log.action_taken = f"error: {str(e)[:80]}"
        log.processed = False
        db.commit()
        return {"status": "error", "message": str(e)}


# ============================================
# ROOT & HEALTH ENDPOINTS
# ============================================

@app.get("/")
async def root():
    return {
        "name": "Iron Lady WATI Analytics API",
        "version": "6.1.0",
        "status": "running",
        "features": ["ticket_system", "counsellor_replies", "conversation_tracking", "broadcast_tracking"],
        "docs": "/docs"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        user_count = db.query(User).count()
        ticket_count = db.query(Ticket).count()
        pending_tickets = db.query(Ticket).filter(Ticket.status == "pending").count()
        return {
            "status": "healthy",
            "database": "connected",
            "total_users": user_count,
            "total_tickets": ticket_count,
            "pending_tickets": pending_tickets,
            "wati_configured": bool(WATI_API_TOKEN),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ============================================
# TICKET ENDPOINTS
# ============================================

@app.get("/api/tickets")
async def get_all_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(Ticket).join(User)
    
    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)
    
    tickets = query.order_by(Ticket.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for t in tickets:
        last_msg_time = t.last_user_message_at or t.created_at
        time_since = datetime.utcnow() - last_msg_time
        hours_remaining = max(0, 24 - (time_since.total_seconds() / 3600))
        
        message_count = db.query(TicketMessage).filter(TicketMessage.ticket_id == t.id).count()
        
        result.append({
            "id": t.id,
            "ticket_number": t.ticket_number,
            "user_id": t.user_id,
            "user_name": t.user.name,
            "user_phone": t.user.phone_number,
            "user_email": t.user.email,
            "category": t.category,
            "initial_message": t.initial_message,
            "status": t.status,
            "message_count": message_count,
            "is_24hr_active": hours_remaining > 0,
            "hours_remaining": round(hours_remaining, 1),
            "created_at": convert_to_ist(t.created_at),
            "updated_at": convert_to_ist(t.updated_at),
            "last_user_message_at": convert_to_ist(t.last_user_message_at),
            "last_counsellor_reply_at": convert_to_ist(t.last_counsellor_reply_at),
            "resolved_at": convert_to_ist(t.resolved_at),
            "resolved_by": t.resolved_by
        })
    
    total = db.query(Ticket).count()
    pending = db.query(Ticket).filter(Ticket.status == "pending").count()
    in_progress = db.query(Ticket).filter(Ticket.status == "in_progress").count()
    resolved = db.query(Ticket).filter(Ticket.status == "resolved").count()
    queries = db.query(Ticket).filter(Ticket.category == "query").count()
    concerns = db.query(Ticket).filter(Ticket.category == "concern").count()
    
    return {
        "tickets": result,
        "stats": {
            "total": total,
            "pending": pending,
            "in_progress": in_progress,
            "resolved": resolved,
            "queries": queries,
            "concerns": concerns
        }
    }


@app.get("/api/tickets/{ticket_id}")
async def get_ticket_details(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    messages = db.query(TicketMessage).filter(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at.asc()).all()
    
    last_msg_time = ticket.last_user_message_at or ticket.created_at
    time_since = datetime.utcnow() - last_msg_time
    hours_remaining = max(0, 24 - (time_since.total_seconds() / 3600))
    
    return {
        "ticket": {
            "id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "category": ticket.category,
            "initial_message": ticket.initial_message,
            "status": ticket.status,
            "is_24hr_active": hours_remaining > 0,
            "hours_remaining": round(hours_remaining, 1),
            "created_at": convert_to_ist(ticket.created_at),
            "updated_at": convert_to_ist(ticket.updated_at),
            "resolved_at": convert_to_ist(ticket.resolved_at),
            "resolved_by": ticket.resolved_by,
            "resolution_notes": ticket.resolution_notes
        },
        "user": {
            "id": ticket.user.id,
            "name": ticket.user.name,
            "phone_number": ticket.user.phone_number,
            "email": ticket.user.email,
            "participation_level": ticket.user.participation_level
        },
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "message_type": m.message_type,
                "message_text": m.message_text,
                "media_url": m.media_url,
                "media_filename": m.media_filename,
                "sent_by": m.sent_by,
                "delivery_status": m.delivery_status,
                "created_at": convert_to_ist(m.created_at)
            }
            for m in messages
        ]
    }


@app.post("/api/tickets/{ticket_id}/reply")
async def send_ticket_reply(ticket_id: int, reply: TicketReplyRequest, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status == "resolved":
        raise HTTPException(status_code=400, detail="Cannot reply to resolved ticket")
    
    last_msg_time = ticket.last_user_message_at or ticket.created_at
    hours_since = (datetime.utcnow() - last_msg_time).total_seconds() / 3600
    
    if hours_since > 24:
        raise HTTPException(status_code=400, detail="24-hour window has expired. Cannot send session message.")
    
    phone_number = ticket.user.phone_number
    
    # Send message with buttons
    full_message = f"{reply.message}\n\n───────────────────\nAre you satisfied with this response?"
    buttons = [{"text": "Yes, Resolved"}, {"text": "Need More Help"}]
    
    result = send_wati_interactive_buttons(phone_number, full_message, buttons)
    
    if result["success"]:
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
        
        return {
            "success": True,
            "message": "Reply sent successfully",
            "message_id": result.get("message_id"),
            "ticket_status": "in_progress"
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {result.get('error')}")


@app.post("/api/tickets/{ticket_id}/reply-media")
async def send_ticket_media_reply(
    ticket_id: int,
    media_url: str = Form(...),
    caption: str = Form(""),
    media_type: str = Form("image"),
    counsellor_name: str = Form("Counsellor"),
    db: Session = Depends(get_db)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status == "resolved":
        raise HTTPException(status_code=400, detail="Cannot reply to resolved ticket")
    
    last_msg_time = ticket.last_user_message_at or ticket.created_at
    hours_since = (datetime.utcnow() - last_msg_time).total_seconds() / 3600
    
    if hours_since > 24:
        raise HTTPException(status_code=400, detail="24-hour window has expired.")
    
    phone_number = ticket.user.phone_number
    result = send_wati_media(phone_number, media_url, caption, media_type)
    
    if result["success"]:
        db.add(TicketMessage(
            ticket_id=ticket.id,
            direction="outgoing",
            message_type=media_type,
            message_text=caption,
            media_url=media_url,
            sent_by=counsellor_name,
            wati_message_id=result.get("message_id"),
            delivery_status="sent"
        ))
        
        ticket.status = "in_progress"
        ticket.last_counsellor_reply_at = datetime.utcnow()
        db.commit()
        
        # Send satisfaction buttons
        send_wati_interactive_buttons(phone_number, "Are you satisfied with this response?", [{"text": "Yes, Resolved"}, {"text": "Need More Help"}])
        
        return {"success": True, "message": "Media sent successfully", "message_id": result.get("message_id")}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send media: {result.get('error')}")


@app.patch("/api/tickets/{ticket_id}/status")
async def update_ticket_status(ticket_id: int, update: TicketStatusUpdateRequest, db: Session = Depends(get_db)):
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
    if update.resolution_notes:
        ticket.resolution_notes = update.resolution_notes
    
    db.commit()
    return {"success": True, "ticket_number": ticket.ticket_number, "new_status": update.status}


# ============================================
# USER ENDPOINTS
# ============================================

@app.get("/api/users")
async def get_all_users(
    skip: int = 0,
    limit: int = 500,
    participation_level: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(User)
    if participation_level:
        query = query.filter(User.participation_level == participation_level)
    
    users = query.order_by(User.last_interaction.desc()).offset(skip).limit(limit).all()
    
    result = []
    for user in users:
        courses = [c[0] for c in db.query(CourseInterest.course_name).filter(CourseInterest.user_id == user.id).distinct().all()]
        total_tickets = db.query(Ticket).filter(Ticket.user_id == user.id).count()
        pending_tickets = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.status.in_(["pending", "in_progress"])).count()
        latest_feedback = db.query(Feedback).filter(Feedback.user_id == user.id).order_by(Feedback.created_at.desc()).first()
        
        result.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "has_active_ticket": user.has_active_ticket,
            "total_tickets": total_tickets,
            "pending_tickets": pending_tickets,
            "course_interests": courses,
            "feedback": latest_feedback.feedback_text if latest_feedback else None,
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction)
        })
    
    return {"users": result, "total": len(result)}


@app.get("/api/users/{user_id}")
async def get_user_details(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    course_interests = db.query(CourseInterest).filter(CourseInterest.user_id == user.id).all()
    tickets = db.query(Ticket).filter(Ticket.user_id == user.id).order_by(Ticket.created_at.desc()).all()
    feedbacks = db.query(Feedback).filter(Feedback.user_id == user.id).order_by(Feedback.created_at.desc()).all()
    
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "has_active_ticket": user.has_active_ticket,
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction)
        },
        "course_interests": [
            {"course_name": ci.course_name, "click_count": ci.click_count, "first_clicked": convert_to_ist(ci.first_clicked), "last_clicked": convert_to_ist(ci.last_clicked)}
            for ci in course_interests
        ],
        "tickets": [
            {"id": t.id, "ticket_number": t.ticket_number, "category": t.category, "status": t.status, "initial_message": t.initial_message[:100] + "..." if len(t.initial_message) > 100 else t.initial_message, "created_at": convert_to_ist(t.created_at)}
            for t in tickets
        ],
        "feedbacks": [
            {"id": f.id, "feedback_text": f.feedback_text, "created_at": convert_to_ist(f.created_at)}
            for f in feedbacks
        ]
    }


# ============================================
# COURSE INTEREST ENDPOINTS
# ============================================

@app.get("/api/course-interests")
async def get_course_interests_summary(db: Session = Depends(get_db)):
    courses = ["LEP", "100BM", "MBW", "Masterclass"]
    result = []
    for course in courses:
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(CourseInterest.course_name == course).scalar() or 0
        unique_users = db.query(CourseInterest).filter(CourseInterest.course_name == course).count()
        result.append({"course_name": course, "total_clicks": int(total_clicks), "unique_users": unique_users})
    return {"course_interests": result}


@app.get("/api/course-interests/{course_name}")
async def get_course_interest_users(course_name: str, db: Session = Depends(get_db)):
    interests = db.query(CourseInterest).join(User).filter(CourseInterest.course_name == course_name).order_by(CourseInterest.click_count.desc()).all()
    result = [
        {"user_id": ci.user.id, "name": ci.user.name, "email": ci.user.email, "phone_number": ci.user.phone_number, "click_count": ci.click_count, "first_clicked": convert_to_ist(ci.first_clicked), "last_clicked": convert_to_ist(ci.last_clicked)}
        for ci in interests
    ]
    return {"course_name": course_name, "users": result, "total_users": len(result), "total_clicks": sum(u["click_count"] for u in result)}


# ============================================
# FEEDBACK ENDPOINTS
# ============================================

@app.get("/api/feedbacks")
async def get_all_feedbacks(skip: int = 0, limit: int = 500, db: Session = Depends(get_db)):
    feedbacks = db.query(Feedback).join(User).order_by(Feedback.created_at.desc()).offset(skip).limit(limit).all()
    result = [
        {"id": f.id, "user_id": f.user.id, "user_name": f.user.name, "user_phone": f.user.phone_number, "user_email": f.user.email, "feedback_text": f.feedback_text, "created_at": convert_to_ist(f.created_at)}
        for f in feedbacks
    ]
    return {"feedbacks": result, "total": len(result)}


# ============================================
# BROADCAST ENDPOINTS
# ============================================

@app.get("/api/broadcasts")
async def get_all_broadcasts(status: Optional[str] = None, skip: int = 0, limit: int = 500, db: Session = Depends(get_db)):
    query = db.query(BroadcastMessage)
    if status:
        query = query.filter(BroadcastMessage.status == status)
    
    broadcasts = query.order_by(BroadcastMessage.sent_at.desc()).offset(skip).limit(limit).all()
    result = [
        {
            "id": b.id, "phone_number": b.phone_number, "recipient_name": b.recipient_name, "message_text": b.message_text,
            "message_type": b.message_type, "status": b.status, "failure_reason": b.failure_reason, "manually_sent": b.manually_sent,
            "manually_sent_at": convert_to_ist(b.manually_sent_at), "manually_sent_by": b.manually_sent_by,
            "sent_at": convert_to_ist(b.sent_at), "delivered_at": convert_to_ist(b.delivered_at), "failed_at": convert_to_ist(b.failed_at)
        }
        for b in broadcasts
    ]
    return {"broadcasts": result, "total": len(result)}


@app.get("/api/broadcasts/failed")
async def get_failed_broadcasts(skip: int = 0, limit: int = 500, db: Session = Depends(get_db)):
    broadcasts = db.query(BroadcastMessage).filter(BroadcastMessage.status == "failed", BroadcastMessage.manually_sent == False).order_by(BroadcastMessage.failed_at.desc()).offset(skip).limit(limit).all()
    result = [
        {"id": b.id, "phone_number": b.phone_number, "recipient_name": b.recipient_name, "message_text": b.message_text, "message_type": b.message_type, "failure_reason": b.failure_reason, "failed_at": convert_to_ist(b.failed_at), "sent_at": convert_to_ist(b.sent_at)}
        for b in broadcasts
    ]
    return {"failed_broadcasts": result, "total": len(result)}


@app.get("/api/broadcasts/stats")
async def get_broadcast_stats(db: Session = Depends(get_db)):
    return {
        "total": db.query(BroadcastMessage).count(),
        "sent": db.query(BroadcastMessage).filter(BroadcastMessage.status == "sent").count(),
        "delivered": db.query(BroadcastMessage).filter(BroadcastMessage.status == "delivered").count(),
        "read": db.query(BroadcastMessage).filter(BroadcastMessage.status == "read").count(),
        "failed": db.query(BroadcastMessage).filter(BroadcastMessage.status == "failed").count(),
        "manually_sent": db.query(BroadcastMessage).filter(BroadcastMessage.manually_sent == True).count(),
        "pending_manual_send": db.query(BroadcastMessage).filter(BroadcastMessage.status == "failed", BroadcastMessage.manually_sent == False).count()
    }


@app.patch("/api/broadcasts/{broadcast_id}/mark-resent")
async def mark_broadcast_as_manually_sent(broadcast_id: int, request: BroadcastMarkResentRequest, db: Session = Depends(get_db)):
    broadcast = db.query(BroadcastMessage).filter(BroadcastMessage.id == broadcast_id).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    broadcast.manually_sent = True
    broadcast.manually_sent_at = datetime.utcnow()
    broadcast.manually_sent_by = request.manually_sent_by
    db.commit()
    return {"status": "success", "broadcast_id": broadcast_id, "manually_sent": True}


# ============================================
# ANALYTICS SUMMARY
# ============================================

@app.get("/api/analytics/summary")
async def get_analytics_summary(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    new_users = db.query(User).filter(User.participation_level == "New to platform").count()
    enrolled_users = db.query(User).filter(User.participation_level == "Enrolled Participant").count()
    
    enrolled_by_program = {program: db.query(User).filter(User.enrolled_program.ilike(f"%{program}%")).count() for program in ["LEP", "100BM", "MBW", "Masterclass"]}
    
    course_stats = []
    for course in ["LEP", "100BM", "MBW", "Masterclass"]:
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(CourseInterest.course_name == course).scalar() or 0
        unique_users = db.query(CourseInterest).filter(CourseInterest.course_name == course).count()
        course_stats.append({"course": course, "total_clicks": int(total_clicks), "unique_users": unique_users})
    
    return {
        "users": {"total": total_users, "new": new_users, "enrolled": enrolled_users, "enrolled_by_program": enrolled_by_program},
        "tickets": {
            "total": db.query(Ticket).count(),
            "pending": db.query(Ticket).filter(Ticket.status == "pending").count(),
            "in_progress": db.query(Ticket).filter(Ticket.status == "in_progress").count(),
            "resolved": db.query(Ticket).filter(Ticket.status == "resolved").count(),
            "queries": db.query(Ticket).filter(Ticket.category == "query").count(),
            "concerns": db.query(Ticket).filter(Ticket.category == "concern").count()
        },
        "feedbacks": {"total": db.query(Feedback).count()},
        "broadcasts": {"total": db.query(BroadcastMessage).count(), "failed_pending": db.query(BroadcastMessage).filter(BroadcastMessage.status == "failed", BroadcastMessage.manually_sent == False).count()},
        "course_interests": course_stats
    }


# ============================================
# WEBHOOK LOGS
# ============================================

@app.get("/api/webhook-logs")
async def get_webhook_logs(limit: int = 50, is_outgoing: Optional[bool] = None, db: Session = Depends(get_db)):
    query = db.query(WebhookLog)
    if is_outgoing is not None:
        query = query.filter(WebhookLog.is_outgoing == is_outgoing)
    
    logs = query.order_by(WebhookLog.created_at.desc()).limit(limit).all()
    return {
        "logs": [
            {"id": log.id, "event_type": log.event_type, "phone_number": log.phone_number, "is_outgoing": log.is_outgoing, "action_taken": log.action_taken, "processed": log.processed, "created_at": convert_to_ist(log.created_at)}
            for log in logs
        ]
    }


@app.get("/api/webhook-logs/{log_id}/raw")
async def get_webhook_log_raw(log_id: int, db: Session = Depends(get_db)):
    log = db.query(WebhookLog).filter(WebhookLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    return {"id": log.id, "raw_data": json.loads(log.raw_data) if log.raw_data else None}


# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    print()
    print("=" * 60)
    print("🚀 Iron Lady WATI Analytics API v6.1.0 - Production Ready")
    print("=" * 60)
    print()
    print(f"📍 Server: http://{API_HOST}:{API_PORT}")
    print(f"📚 API Docs: http://{API_HOST}:{API_PORT}/docs")
    print()
    print(f"🔑 WATI: {'Configured ✅' if WATI_API_TOKEN else 'NOT SET ❌'}")
    print()
    
    uvicorn.run(app, host=API_HOST, port=API_PORT)
