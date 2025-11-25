"""
Iron Lady WATI Analytics - Complete Backend
FastAPI server with WATI webhook receiver and analytics API

Author: Iron Lady Tech Team
Version: 4.0.0 - Added Broadcast Message Tracking
"""

import json
import re
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
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

# ============================================
# DATABASE SETUP
# ============================================

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================
# TIMEZONE HELPER
# ============================================

def convert_to_ist(utc_dt):
    """Convert UTC datetime to IST (Indian Standard Time)"""
    if utc_dt is None:
        return None
    
    # If datetime is naive (no timezone), assume it's UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC"))
    
    # Convert to IST
    ist_dt = utc_dt.astimezone(ZoneInfo("Asia/Kolkata"))
    return ist_dt.isoformat()

# ============================================
# DATABASE MODELS
# ============================================

class User(Base):
    """User/Lead model - stores all contact information"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True)
    participation_level = Column(String(50), default="Unknown")
    enrolled_program = Column(String(100), nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_interaction = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    course_interests = relationship("CourseInterest", back_populates="user", cascade="all, delete-orphan")
    queries = relationship("UserQuery", back_populates="user", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")


class CourseInterest(Base):
    """Tracks which courses users are interested in"""
    __tablename__ = "course_interests"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_name = Column(String(50), nullable=False)
    click_count = Column(Integer, default=1)
    first_clicked = Column(DateTime, default=datetime.utcnow)
    last_clicked = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="course_interests")


class UserQuery(Base):
    """Stores user queries and counsellor requests"""
    __tablename__ = "user_queries"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_text = Column(Text, nullable=False)
    query_type = Column(String(30), default="general")
    contact_preference = Column(String(20), default="message")
    status = Column(String(30), default="pending")
    resolved_by = Column(String(100), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="queries")


class Feedback(Base):
    """Stores user feedbacks"""
    __tablename__ = "feedbacks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    feedback_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="feedbacks")


class BroadcastMessage(Base):
    """Tracks broadcast messages and their delivery status"""
    __tablename__ = "broadcast_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), nullable=False, index=True)
    recipient_name = Column(String(100), nullable=True)
    message_text = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")  # text, image, document, etc.
    
    # Media info (if applicable)
    media_url = Column(String(500), nullable=True)
    caption = Column(Text, nullable=True)
    
    # Delivery tracking
    status = Column(String(20), default="sent", index=True)  # sent, delivered, read, failed, pending
    wati_message_id = Column(String(100), unique=True, nullable=True, index=True)
    
    # Failed message details
    failure_reason = Column(String(500), nullable=True)
    failed_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Manual resend tracking
    manually_sent = Column(Boolean, default=False)
    manually_sent_at = Column(DateTime, nullable=True)
    manually_sent_by = Column(String(100), nullable=True)
    
    # Timestamps
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookLog(Base):
    """Logs all webhook events for debugging"""
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
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Define columns that might need to be added
    column_updates = [
        ("users", "enrolled_program", "VARCHAR(100)"),
        ("users", "participation_level", "VARCHAR(50) DEFAULT 'Unknown'"),
        ("user_queries", "query_type", "VARCHAR(30) DEFAULT 'general'"),
        ("user_queries", "contact_preference", "VARCHAR(20) DEFAULT 'message'"),
        ("user_queries", "resolved_by", "VARCHAR(100)"),
        ("user_queries", "resolution_notes", "TEXT"),
        ("user_queries", "updated_at", "TIMESTAMP DEFAULT NOW()"),
        ("webhook_logs", "is_outgoing", "BOOLEAN DEFAULT FALSE"),
        ("webhook_logs", "action_taken", "VARCHAR(100)"),
        ("feedbacks", "created_at", "TIMESTAMP DEFAULT NOW()"),
        ("course_interests", "click_count", "INTEGER DEFAULT 1"),
        ("course_interests", "first_clicked", "TIMESTAMP DEFAULT NOW()"),
        ("course_interests", "last_clicked", "TIMESTAMP DEFAULT NOW()"),
        # Broadcast message columns
        ("broadcast_messages", "media_url", "VARCHAR(500)"),
        ("broadcast_messages", "caption", "TEXT"),
        ("broadcast_messages", "manually_sent", "BOOLEAN DEFAULT FALSE"),
        ("broadcast_messages", "manually_sent_at", "TIMESTAMP"),
        ("broadcast_messages", "manually_sent_by", "VARCHAR(100)"),
        ("broadcast_messages", "updated_at", "TIMESTAMP DEFAULT NOW()"),
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
                            print(f"   ✅ Added column: {table}.{column}")
                        except Exception as e:
                            pass
            conn.commit()
        
        print("✅ Database ready!")
        
    except Exception as e:
        print(f"⚠️ Database init warning: {e}")


# Initialize database
init_database()

# ============================================
# FASTAPI APP
# ============================================

app = FastAPI(
    title="Iron Lady WATI Analytics API",
    description="Complete analytics backend for WATI WhatsApp chatbot with broadcast tracking",
    version="4.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
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
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================
# PYDANTIC MODELS
# ============================================

class QueryUpdateRequest(BaseModel):
    """Request model for updating query status"""
    status: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


class BroadcastMarkResentRequest(BaseModel):
    """Request model for marking broadcast as manually sent"""
    manually_sent_by: Optional[str] = "Dashboard User"


# ============================================
# HELPER FUNCTIONS
# ============================================

IGNORE_MESSAGES = {
    "hi", "hello", "hey", "hii", "hiii", "helloo", "hellooo",
    "good morning", "good night", "good evening", "gm", "gn",
    "morning", "night", "evening",
    "bye", "byee", "goodbye",
    "thanks", "thank you", "thankyou", "thnx", "thx", "ty",
    "ok", "okay", "k", "oky",
    "yes", "no", "ya", "yep", "nope", "yup",
    "hmm", "hm", "mm",
    "cool", "nice", "great", "awesome", "sure", "alright", "fine",
    "good", "bad", "np"
}


def get_or_create_user(db: Session, phone_number: str, name: str = None, email: str = None) -> User:
    """Get existing user or create new one"""
    phone_number = phone_number.replace("+", "").replace(" ", "").strip()
    
    user = db.query(User).filter(User.phone_number == phone_number).first()
    
    if not user:
        user = User(
            phone_number=phone_number,
            name=name,
            email=email,
            participation_level="Unknown"
        )
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


def update_course_interest(db: Session, user_id: int, course_name: str):
    """Update or create course interest record"""
    interest = db.query(CourseInterest).filter(
        CourseInterest.user_id == user_id,
        CourseInterest.course_name == course_name
    ).first()
    
    if interest:
        interest.click_count += 1
        interest.last_clicked = datetime.utcnow()
    else:
        interest = CourseInterest(
            user_id=user_id,
            course_name=course_name
        )
        db.add(interest)
    
    db.commit()


def add_enrolled_program(user: User, program: str):
    """Add program to user's enrolled_program"""
    if not user.enrolled_program:
        user.enrolled_program = program
    elif program not in user.enrolled_program:
        user.enrolled_program = f"{user.enrolled_program},{program}"


def should_ignore_message(message: str) -> bool:
    """Check if message is casual greeting"""
    message_lower = message.lower().strip()
    return message_lower in IGNORE_MESSAGES or len(message.strip()) < 3


def extract_email(text: str) -> Optional[str]:
    """Extract email address from text"""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, text)
    return match.group() if match else None


def check_counsellor_flow_context(db: Session, wa_number: str) -> bool:
    """Check if user is in counsellor request flow"""
    recent_logs = db.query(WebhookLog).filter(
        WebhookLog.phone_number == wa_number,
        WebhookLog.is_outgoing == True,
        WebhookLog.created_at >= datetime.utcnow() - timedelta(minutes=30)
    ).order_by(WebhookLog.created_at.desc()).limit(10).all()
    
    for rlog in recent_logs:
        if rlog.raw_data:
            try:
                rdata = json.loads(rlog.raw_data)
                rtext = (rdata.get("text", "") or "").lower()
                
                if any(phrase in rtext for phrase in [
                    "please share any queries or doubts",
                    "queries or doubts you may have",
                    "counsellor will reach out",
                    "counsellor will call",
                    "connect you with a counsellor"
                ]):
                    return True
                    
                if rlog.action_taken in ["query_prompt_sent", "counsellor_confirmed"]:
                    return True
                    
            except:
                pass
    
    return False


def check_feedback_flow_context(db: Session, wa_number: str) -> bool:
    """Check if user is in feedback flow"""
    recent_logs = db.query(WebhookLog).filter(
        WebhookLog.phone_number == wa_number,
        WebhookLog.is_outgoing == True,
        WebhookLog.created_at >= datetime.utcnow() - timedelta(minutes=30)
    ).order_by(WebhookLog.created_at.desc()).limit(5).all()
    
    for rlog in recent_logs:
        if rlog.raw_data:
            try:
                rdata = json.loads(rlog.raw_data)
                rtext = (rdata.get("text", "") or "").lower()
                
                if any(phrase in rtext for phrase in [
                    "please provide your feedback",
                    "share your feedback",
                    "give us your feedback"
                ]):
                    return True
                    
                if rlog.action_taken == "feedback_prompt_sent":
                    return True
                    
            except:
                pass
    
    return False


def message_looks_like_query(message: str) -> bool:
    """Check if message looks like a genuine query"""
    message_lower = message.lower()
    
    if "?" in message:
        return True
    
    if len(message) > 30:
        return True
    
    query_keywords = [
        "query", "doubt", "question", "help", "issue", "problem",
        "need", "want to know", "please tell", "can you", "how to",
        "what is", "when is", "where is", "why is", "who is",
        "tell me", "explain", "clarify", "information", "details"
    ]
    
    if any(keyword in message_lower for keyword in query_keywords):
        return True
    
    return False


# ============================================
# WEBHOOK ENDPOINT - MAIN
# ============================================

@app.post("/webhook/wati")
async def wati_webhook(data: dict, db: Session = Depends(get_db)):
    """
    WATI Webhook Receiver - v4.0.3
    Complete IST timezone support across all endpoints
    """
    
    wa_number = data.get("waId") or data.get("waNumber") or ""
    sender_name = data.get("senderName", "").replace("~", "").strip() or None
    event_type = data.get("eventType", "")
    is_outgoing = data.get("owner", False) == True
    message_text = data.get("text", "") or ""
    message_lower = message_text.lower()
    
    # Get message ID for tracking delivery
    message_id = data.get("id") or data.get("messageId")
    
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
        # ========================================
        # PRIORITY: HANDLE STATUS UPDATES FIRST
        # (These often don't have phone numbers)
        # ========================================
        
        # Template Message Failed - Mark as failed
        if event_type == "templateMessageFailed":
            message_id = data.get("id")
            failed_detail = data.get("failedDetail", "Unknown error")
            failed_code = data.get("failedCode", "")
            
            if message_id:
                broadcast = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id == message_id
                ).first()
                
                if broadcast:
                    broadcast.status = "failed"
                    broadcast.failed_at = datetime.utcnow()
                    broadcast.failure_reason = f"{failed_detail} (Code: {failed_code})" if failed_code else failed_detail
                    broadcast.updated_at = datetime.utcnow()
                    db.commit()
                    log.action_taken = "broadcast_failed_updated"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": "broadcast_failed_updated"}
                else:
                    log.action_taken = "broadcast_not_found_for_failure"
                    log.processed = True
                    db.commit()
                    return {"status": "ignored", "reason": "Broadcast not found"}
        
        # Sent Message Delivered (for template messages)
        if event_type == "sentMessageDELIVERED":
            whatsapp_msg_id = data.get("whatsappMessageId")
            if whatsapp_msg_id:
                # Try to find by whatsappMessageId
                broadcast = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id.like(f"%{whatsapp_msg_id[:20]}%")
                ).first()
                
                if broadcast:
                    broadcast.status = "delivered"
                    broadcast.delivered_at = datetime.utcnow()
                    broadcast.updated_at = datetime.utcnow()
                    db.commit()
                    log.action_taken = "broadcast_delivered_updated"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": "broadcast_delivered_updated"}
        
        # Sent Message Read
        if event_type == "sentMessageREAD":
            whatsapp_msg_id = data.get("whatsappMessageId")
            if whatsapp_msg_id:
                broadcast = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id.like(f"%{whatsapp_msg_id[:20]}%")
                ).first()
                
                if broadcast:
                    broadcast.status = "read"
                    broadcast.read_at = datetime.utcnow()
                    broadcast.updated_at = datetime.utcnow()
                    db.commit()
                    log.action_taken = "broadcast_read_updated"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": "broadcast_read_updated"}
        
        # ========================================
        # NOW CHECK FOR PHONE NUMBER
        # (Required for new messages, not status updates)
        # ========================================
        
        if not wa_number:
            log.action_taken = "ignored_no_phone"
            log.processed = True
            db.commit()
            return {"status": "ignored", "reason": "No phone number"}
        
        wa_number = wa_number.replace("+", "").replace(" ", "")
        
        # ========================================
        # HANDLE NEW TEMPLATE MESSAGE SENT
        # ========================================
        
        # Template Message Sent - Track broadcast
        if event_type == "templateMessageSent_v2":
            message_id = data.get("id")
            wa_id = data.get("waId", "").replace("+", "").replace(" ", "")
            message_text = data.get("text", "")
            template_name = data.get("templateName", "")
            
            if message_id and wa_id and len(message_text) > 0:
                # Check if already tracked
                existing = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id == message_id
                ).first()
                
                if not existing:
                    # Get user info if available
                    user = db.query(User).filter(User.phone_number == wa_id).first()
                    recipient_name = user.name if user else None
                    
                    broadcast = BroadcastMessage(
                        phone_number=wa_id,
                        recipient_name=recipient_name,
                        message_text=message_text,
                        wati_message_id=message_id,
                        message_type="template",
                        status="sent"
                    )
                    db.add(broadcast)
                    db.commit()
                    log.action_taken = "broadcast_tracked"
                else:
                    log.action_taken = "broadcast_already_tracked"
                
                log.processed = True
                db.commit()
                return {"status": "processed", "action": log.action_taken}
        
        # Handle regular delivery status updates (for non-template messages)
        if event_type in ["sent", "delivered", "read", "failed"]:
            if message_id:
                broadcast = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id == message_id
                ).first()
                
                if broadcast:
                    broadcast.status = event_type
                    broadcast.updated_at = datetime.utcnow()
                    
                    if event_type == "delivered":
                        broadcast.delivered_at = datetime.utcnow()
                    elif event_type == "read":
                        broadcast.read_at = datetime.utcnow()
                    elif event_type == "failed":
                        broadcast.failed_at = datetime.utcnow()
                        broadcast.failure_reason = data.get("errorMessage") or data.get("failureReason") or "Unknown error"
                    
                    db.commit()
                    log.action_taken = f"broadcast_{event_type}_updated"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": log.action_taken}
        
        # Get or create user
        user = get_or_create_user(db, wa_number, name=sender_name)
        
        # ========================================
        # HANDLE OUTGOING BOT MESSAGES
        # ========================================
        
        if is_outgoing and message_text:
            
            # Track as potential broadcast message
            # Only track if it looks like a broadcast (not a flow response)
            if len(message_text) > 50 and message_id:  # Broadcasts are typically longer
                # Check if not already tracked
                existing = db.query(BroadcastMessage).filter(
                    BroadcastMessage.wati_message_id == message_id
                ).first()
                
                if not existing:
                    broadcast = BroadcastMessage(
                        phone_number=wa_number,
                        recipient_name=sender_name,
                        message_text=message_text,
                        wati_message_id=message_id,
                        status="sent"
                    )
                    db.add(broadcast)
                    db.commit()
            
            # Enrollment confirmation
            if "thrilled to inform" in message_lower and "registration" in message_lower:
                user.participation_level = "Enrolled Participant"
                
                if "leadership essentials" in message_lower:
                    add_enrolled_program(user, "LEP")
                    log.action_taken = "enrolled_LEP"
                elif "100 board" in message_lower:
                    add_enrolled_program(user, "100BM")
                    log.action_taken = "enrolled_100BM"
                elif "business warfare" in message_lower or "mbw" in message_lower:
                    add_enrolled_program(user, "MBW")
                    log.action_taken = "enrolled_MBW"
                elif "masterclass" in message_lower:
                    add_enrolled_program(user, "Masterclass")
                    log.action_taken = "enrolled_Masterclass"
                else:
                    log.action_taken = "enrolled_unknown"
                
                db.commit()
                log.processed = True
                db.commit()
                return {"status": "processed", "action": log.action_taken}
            
            # Course interests
            if "leadership essentials program enables you to master" in message_lower:
                update_course_interest(db, user.id, "LEP")
                log.action_taken = "course_interest_LEP"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_LEP"}
            
            if "100 board members program enables you to focus" in message_lower:
                update_course_interest(db, user.id, "100BM")
                log.action_taken = "course_interest_100BM"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_100BM"}
            
            if "master of business warfare focuses on winning" in message_lower:
                update_course_interest(db, user.id, "MBW")
                log.action_taken = "course_interest_MBW"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_MBW"}
            
            if "iron lady leadership masterclass helps you" in message_lower:
                update_course_interest(db, user.id, "Masterclass")
                log.action_taken = "course_interest_Masterclass"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_Masterclass"}
            
            # Participation levels
            if "welcome to the iron lady platform" in message_lower:
                user.participation_level = "New to platform"
                db.commit()
                log.action_taken = "participation_new"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "participation_new"}
            
            if "ask a question here" in message_lower:
                user.participation_level = "Enrolled Participant"
                db.commit()
                log.action_taken = "participation_enrolled"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "participation_enrolled"}
            
            # Flow confirmations
            if "counsellor will reach out to you" in message_lower:
                log.action_taken = "counsellor_confirmed"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "counsellor_confirmed"}
            
            if "thank you for your valueable feedback" in message_lower:
                log.action_taken = "feedback_confirmed"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "feedback_confirmed"}
            
            if "please share any queries or doubts" in message_lower:
                log.action_taken = "query_prompt_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "query_prompt_sent"}
            
            if "please provide your feedback here" in message_lower:
                log.action_taken = "feedback_prompt_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "feedback_prompt_sent"}
            
            if "please fill below form" in message_lower:
                log.action_taken = "query_form_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "query_form_sent"}
            
            log.action_taken = "bot_message_logged"
            log.processed = True
            db.commit()
            return {"status": "processed", "action": "bot_message_logged"}
        
        # ========================================
        # HANDLE INCOMING USER MESSAGES
        # ========================================
        
        if not is_outgoing and message_text:
            
            # Email capture
            email = extract_email(message_text)
            if email:
                user.email = email
                db.commit()
                log.action_taken = "email_captured"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "email_captured", "email": email}
            
            # Ignore casual messages
            if should_ignore_message(message_text):
                log.action_taken = "casual_ignored"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "casual_ignored"}
            
            # Check context
            recent_bot_msg = db.query(WebhookLog).filter(
                WebhookLog.phone_number == wa_number,
                WebhookLog.is_outgoing == True
            ).order_by(WebhookLog.created_at.desc()).first()
            
            recent_bot_text = ""
            if recent_bot_msg and recent_bot_msg.raw_data:
                try:
                    recent_data = json.loads(recent_bot_msg.raw_data)
                    recent_bot_text = (recent_data.get("text", "") or "").lower()
                except:
                    pass
            
            # Counsellor query detection
            is_counsellor_query_context = "please share any queries or doubts" in recent_bot_text
            is_in_counsellor_flow = check_counsellor_flow_context(db, wa_number)
            
            five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
            recent_query_exists = db.query(UserQuery).filter(
                UserQuery.user_id == user.id,
                UserQuery.created_at >= five_mins_ago
            ).first() is not None
            
            if is_counsellor_query_context or (is_in_counsellor_flow and not recent_query_exists):
                query = UserQuery(
                    user_id=user.id,
                    query_text=message_text,
                    query_type="counsellor_doubt",
                    contact_preference="call",
                    status="pending"
                )
                db.add(query)
                db.commit()
                log.action_taken = "counsellor_query_created"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "counsellor_query_created"}
            
            # Feedback
            is_feedback_context = "please provide your feedback here" in recent_bot_text
            is_in_feedback_flow = check_feedback_flow_context(db, wa_number)
            
            if is_feedback_context or is_in_feedback_flow:
                recent_feedback_exists = db.query(Feedback).filter(
                    Feedback.user_id == user.id,
                    Feedback.created_at >= five_mins_ago
                ).first() is not None
                
                if not recent_feedback_exists:
                    feedback = Feedback(
                        user_id=user.id,
                        feedback_text=message_text
                    )
                    db.add(feedback)
                    db.commit()
                    log.action_taken = "feedback_created"
                    log.processed = True
                    db.commit()
                    return {"status": "processed", "action": "feedback_created"}
            
            # General query
            if message_looks_like_query(message_text) and not recent_query_exists:
                query = UserQuery(
                    user_id=user.id,
                    query_text=message_text,
                    query_type="general",
                    contact_preference="message",
                    status="pending"
                )
                db.add(query)
                db.commit()
                log.action_taken = "general_query_created"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "general_query_created"}
            
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
    """API root"""
    return {
        "name": "Iron Lady WATI Analytics API",
        "version": "4.0.0",
        "status": "running",
        "features": ["user_tracking", "course_interests", "queries", "feedbacks", "broadcast_tracking"],
        "docs": "/docs"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        user_count = db.query(User).count()
        broadcast_count = db.query(BroadcastMessage).count()
        return {
            "status": "healthy",
            "database": "connected",
            "total_users": user_count,
            "total_broadcasts": broadcast_count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


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
    """Get all users with summary info"""
    query = db.query(User)
    
    if participation_level:
        query = query.filter(User.participation_level == participation_level)
    
    users = query.order_by(User.last_interaction.desc()).offset(skip).limit(limit).all()
    
    result = []
    for user in users:
        courses = db.query(CourseInterest.course_name).filter(
            CourseInterest.user_id == user.id
        ).distinct().all()
        course_list = [c[0] for c in courses]
        
        has_call_request = db.query(UserQuery).filter(
            UserQuery.user_id == user.id,
            UserQuery.contact_preference == "call",
            UserQuery.status == "pending"
        ).first() is not None
        
        has_message_query = db.query(UserQuery).filter(
            UserQuery.user_id == user.id,
            UserQuery.contact_preference == "message",
            UserQuery.status == "pending"
        ).first() is not None
        
        latest_feedback = db.query(Feedback).filter(
            Feedback.user_id == user.id
        ).order_by(Feedback.created_at.desc()).first()
        
        query_count = db.query(UserQuery).filter(UserQuery.user_id == user.id).count()
        
        result.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "has_call_request": has_call_request,
            "has_message_query": has_message_query,
            "course_interests": course_list,
            "feedback": latest_feedback.feedback_text if latest_feedback else None,
            "total_queries": query_count,
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction)
        })
    
    return {"users": result, "total": len(result)}


@app.get("/api/users/{user_id}")
async def get_user_details(user_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a specific user"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    course_interests = db.query(CourseInterest).filter(
        CourseInterest.user_id == user.id
    ).all()
    
    queries = db.query(UserQuery).filter(
        UserQuery.user_id == user.id
    ).order_by(UserQuery.created_at.desc()).all()
    
    feedbacks = db.query(Feedback).filter(
        Feedback.user_id == user.id
    ).order_by(Feedback.created_at.desc()).all()
    
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction)
        },
        "course_interests": [
            {
                "course_name": ci.course_name,
                "click_count": ci.click_count,
                "first_clicked": convert_to_ist(ci.first_clicked),
                "last_clicked": convert_to_ist(ci.last_clicked)
            }
            for ci in course_interests
        ],
        "queries": [
            {
                "id": q.id,
                "query_text": q.query_text,
                "query_type": q.query_type,
                "contact_preference": q.contact_preference,
                "status": q.status,
                "resolved_by": q.resolved_by,
                "resolution_notes": q.resolution_notes,
                "created_at": convert_to_ist(q.created_at)
            }
            for q in queries
        ],
        "feedbacks": [
            {
                "id": f.id,
                "feedback_text": f.feedback_text,
                "created_at": convert_to_ist(f.created_at)
            }
            for f in feedbacks
        ]
    }


# ============================================
# QUERY ENDPOINTS
# ============================================

@app.get("/api/queries")
async def get_all_queries(
    status: Optional[str] = None,
    contact_preference: Optional[str] = None,
    query_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Get all queries with optional filters"""
    query = db.query(UserQuery).join(User)
    
    if status:
        query = query.filter(UserQuery.status == status)
    if contact_preference:
        query = query.filter(UserQuery.contact_preference == contact_preference)
    if query_type:
        query = query.filter(UserQuery.query_type == query_type)
    
    queries = query.order_by(UserQuery.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for q in queries:
        result.append({
            "id": q.id,
            "user_id": q.user_id,
            "user_name": q.user.name,
            "user_phone": q.user.phone_number,
            "user_email": q.user.email,
            "query_text": q.query_text,
            "query_type": q.query_type,
            "contact_preference": q.contact_preference,
            "status": q.status,
            "resolved_by": q.resolved_by,
            "resolution_notes": q.resolution_notes,
            "created_at": convert_to_ist(q.created_at)
        })
    
    total = db.query(UserQuery).count()
    pending = db.query(UserQuery).filter(UserQuery.status == "pending").count()
    
    return {
        "queries": result,
        "total": total,
        "pending": pending,
        "returned": len(result)
    }


@app.patch("/api/queries/{query_id}")
async def update_query_status(
    query_id: int,
    update: QueryUpdateRequest,
    db: Session = Depends(get_db)
):
    """Update query status"""
    query = db.query(UserQuery).filter(UserQuery.id == query_id).first()
    
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    query.status = update.status
    if update.resolved_by:
        query.resolved_by = update.resolved_by
    if update.resolution_notes:
        query.resolution_notes = update.resolution_notes
    
    db.commit()
    
    return {
        "status": "success",
        "query_id": query_id,
        "new_status": update.status
    }


# ============================================
# BROADCAST ENDPOINTS (NEW!)
# ============================================

@app.get("/api/broadcasts")
async def get_all_broadcasts(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Get all broadcast messages with optional status filter"""
    query = db.query(BroadcastMessage)
    
    if status:
        query = query.filter(BroadcastMessage.status == status)
    
    broadcasts = query.order_by(BroadcastMessage.sent_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for b in broadcasts:
        result.append({
            "id": b.id,
            "phone_number": b.phone_number,
            "recipient_name": b.recipient_name,
            "message_text": b.message_text,
            "message_type": b.message_type,
            "status": b.status,
            "failure_reason": b.failure_reason,
            "manually_sent": b.manually_sent,
            "manually_sent_at": convert_to_ist(b.manually_sent_at),
            "manually_sent_by": b.manually_sent_by,
            "sent_at": convert_to_ist(b.sent_at),
            "delivered_at": convert_to_ist(b.delivered_at),
            "failed_at": convert_to_ist(b.failed_at)
        })
    
    return {"broadcasts": result, "total": len(result)}


@app.get("/api/broadcasts/failed")
async def get_failed_broadcasts(
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Get only failed broadcast messages"""
    broadcasts = db.query(BroadcastMessage).filter(
        BroadcastMessage.status == "failed",
        BroadcastMessage.manually_sent == False
    ).order_by(BroadcastMessage.failed_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for b in broadcasts:
        result.append({
            "id": b.id,
            "phone_number": b.phone_number,
            "recipient_name": b.recipient_name,
            "message_text": b.message_text,
            "message_type": b.message_type,
            "failure_reason": b.failure_reason,
            "failed_at": convert_to_ist(b.failed_at),
            "sent_at": convert_to_ist(b.sent_at)
        })
    
    return {"failed_broadcasts": result, "total": len(result)}


@app.get("/api/broadcasts/stats")
async def get_broadcast_stats(db: Session = Depends(get_db)):
    """Get broadcast statistics"""
    total = db.query(BroadcastMessage).count()
    sent = db.query(BroadcastMessage).filter(BroadcastMessage.status == "sent").count()
    delivered = db.query(BroadcastMessage).filter(BroadcastMessage.status == "delivered").count()
    read = db.query(BroadcastMessage).filter(BroadcastMessage.status == "read").count()
    failed = db.query(BroadcastMessage).filter(BroadcastMessage.status == "failed").count()
    manually_sent = db.query(BroadcastMessage).filter(BroadcastMessage.manually_sent == True).count()
    
    # Failed but not manually sent yet
    pending_manual = db.query(BroadcastMessage).filter(
        BroadcastMessage.status == "failed",
        BroadcastMessage.manually_sent == False
    ).count()
    
    return {
        "total": total,
        "sent": sent,
        "delivered": delivered,
        "read": read,
        "failed": failed,
        "manually_sent": manually_sent,
        "pending_manual_send": pending_manual
    }


@app.patch("/api/broadcasts/{broadcast_id}/mark-resent")
async def mark_broadcast_as_manually_sent(
    broadcast_id: int,
    request: BroadcastMarkResentRequest,
    db: Session = Depends(get_db)
):
    """Mark a failed broadcast as manually sent via personal WhatsApp"""
    broadcast = db.query(BroadcastMessage).filter(BroadcastMessage.id == broadcast_id).first()
    
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    broadcast.manually_sent = True
    broadcast.manually_sent_at = datetime.utcnow()
    broadcast.manually_sent_by = request.manually_sent_by
    
    db.commit()
    
    return {
        "status": "success",
        "broadcast_id": broadcast_id,
        "manually_sent": True,
        "manually_sent_by": request.manually_sent_by
    }


# ============================================
# COURSE INTEREST ENDPOINTS
# ============================================

@app.get("/api/course-interests")
async def get_course_interests_summary(db: Session = Depends(get_db)):
    """Get summary of course interests"""
    courses = ["LEP", "100BM", "MBW", "Masterclass"]
    
    result = []
    for course in courses:
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(
            CourseInterest.course_name == course
        ).scalar() or 0
        
        unique_users = db.query(CourseInterest).filter(
            CourseInterest.course_name == course
        ).count()
        
        result.append({
            "course_name": course,
            "total_clicks": int(total_clicks),
            "unique_users": unique_users
        })
    
    return {"course_interests": result}


@app.get("/api/course-interests/{course_name}")
async def get_course_interest_users(course_name: str, db: Session = Depends(get_db)):
    """Get all users interested in a specific course"""
    interests = db.query(CourseInterest).join(User).filter(
        CourseInterest.course_name == course_name
    ).order_by(CourseInterest.click_count.desc()).all()
    
    result = []
    for ci in interests:
        result.append({
            "user_id": ci.user.id,
            "name": ci.user.name,
            "email": ci.user.email,
            "phone_number": ci.user.phone_number,
            "click_count": ci.click_count,
            "first_clicked": convert_to_ist(ci.first_clicked),
            "last_clicked": convert_to_ist(ci.last_clicked)
        })
    
    return {
        "course_name": course_name,
        "users": result,
        "total_users": len(result),
        "total_clicks": sum(u["click_count"] for u in result)
    }


# ============================================
# FEEDBACK ENDPOINTS
# ============================================

@app.get("/api/feedbacks")
async def get_all_feedbacks(
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Get all feedbacks"""
    feedbacks = db.query(Feedback).join(User).order_by(
        Feedback.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    result = []
    for f in feedbacks:
        result.append({
            "id": f.id,
            "user_id": f.user.id,
            "user_name": f.user.name,
            "user_phone": f.user.phone_number,
            "user_email": f.user.email,
            "feedback_text": f.feedback_text,
            "created_at": convert_to_ist(f.created_at)
        })
    
    return {"feedbacks": result, "total": len(result)}


# ============================================
# ANALYTICS SUMMARY ENDPOINT
# ============================================

@app.get("/api/analytics/summary")
async def get_analytics_summary(db: Session = Depends(get_db)):
    """Get overall analytics summary for dashboard"""
    
    total_users = db.query(User).count()
    new_users = db.query(User).filter(User.participation_level == "New to platform").count()
    enrolled_users = db.query(User).filter(User.participation_level == "Enrolled Participant").count()
    
    enrolled_by_program = {}
    for program in ["LEP", "100BM", "MBW", "Masterclass"]:
        count = db.query(User).filter(
            User.enrolled_program.ilike(f"%{program}%")
        ).count()
        enrolled_by_program[program] = count
    
    total_queries = db.query(UserQuery).count()
    pending_queries = db.query(UserQuery).filter(UserQuery.status == "pending").count()
    call_requests = db.query(UserQuery).filter(UserQuery.contact_preference == "call").count()
    counsellor_doubts = db.query(UserQuery).filter(UserQuery.query_type == "counsellor_doubt").count()
    
    total_feedbacks = db.query(Feedback).count()
    
    course_stats = []
    for course in ["LEP", "100BM", "MBW", "Masterclass"]:
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(
            CourseInterest.course_name == course
        ).scalar() or 0
        
        unique_users = db.query(CourseInterest).filter(
            CourseInterest.course_name == course
        ).count()
        
        course_stats.append({
            "course": course,
            "total_clicks": int(total_clicks),
            "unique_users": unique_users
        })
    
    # Broadcast stats
    total_broadcasts = db.query(BroadcastMessage).count()
    failed_broadcasts = db.query(BroadcastMessage).filter(
        BroadcastMessage.status == "failed",
        BroadcastMessage.manually_sent == False
    ).count()
    
    return {
        "users": {
            "total": total_users,
            "new": new_users,
            "enrolled": enrolled_users,
            "enrolled_by_program": enrolled_by_program
        },
        "queries": {
            "total": total_queries,
            "pending": pending_queries,
            "call_requests": call_requests,
            "counsellor_doubts": counsellor_doubts
        },
        "feedbacks": {
            "total": total_feedbacks
        },
        "broadcasts": {
            "total": total_broadcasts,
            "failed_pending": failed_broadcasts
        },
        "course_interests": course_stats
    }


# ============================================
# WEBHOOK LOGS ENDPOINT
# ============================================

@app.get("/api/webhook-logs")
async def get_webhook_logs(
    limit: int = 50,
    is_outgoing: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Get webhook logs for debugging"""
    query = db.query(WebhookLog)
    
    if is_outgoing is not None:
        query = query.filter(WebhookLog.is_outgoing == is_outgoing)
    
    logs = query.order_by(WebhookLog.created_at.desc()).limit(limit).all()
    
    return {
        "logs": [
            {
                "id": log.id,
                "event_type": log.event_type,
                "phone_number": log.phone_number,
                "is_outgoing": log.is_outgoing,
                "action_taken": log.action_taken,
                "processed": log.processed,
                "created_at": convert_to_ist(log.created_at)
            }
            for log in logs
        ]
    }


@app.get("/api/webhook-logs/{log_id}/raw")
async def get_webhook_log_raw(log_id: int, db: Session = Depends(get_db)):
    """Get raw webhook data for a specific log"""
    log = db.query(WebhookLog).filter(WebhookLog.id == log_id).first()
    
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    return {
        "id": log.id,
        "raw_data": json.loads(log.raw_data) if log.raw_data else None
    }


# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    print()
    print("=" * 50)
    print("🚀 Iron Lady WATI Analytics API v4.0.3")
    print("=" * 50)
    print()
    print(f"📍 Server: http://{API_HOST}:{API_PORT}")
    print(f"📚 API Docs: http://{API_HOST}:{API_PORT}/docs")
    print(f"🔗 Webhook URL: http://your-server:{API_PORT}/webhook/wati")
    print()
    print("✨ New Features:")
    print("   - Broadcast message tracking")
    print("   - Failed message detection")
    print("   - Manual resend tracking")
    print()
    print("=" * 50)
    print()
    
    uvicorn.run(app, host=API_HOST, port=API_PORT)