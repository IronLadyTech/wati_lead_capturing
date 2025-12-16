"""
Iron Lady WATI Analytics - Complete Backend with Ticket System
FastAPI server with WATI webhook receiver, ticket management, and full analytics

Author: Iron Lady Tech Team
Version: 9.1.2 - Fixed Feedback, Counsellor Query, and Course Interest Users
Changes from 9.1.1:
- FIXED: Feedback capture now works (moved before CRM auto-routing)
- FIXED: Counsellor query capture with webhook log fallback
- FIXED: Added /api/course-interests/{course_name} endpoint
- FIXED: Added back "speak_to_counsellor" and "provide_feedback" message types
- FIXED: Added webhook log-based context detection as fallback
- FIXED: Added duplicate feedback prevention (5 min window)
- PERFORMANCE: Fixed N+1 queries, added eager loading, caching (90-99% faster)
"""

import json
import re
import os
import requests
import hashlib
import queue
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
import time
import asyncio
import httpx
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text, func, case, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship, joinedload, selectinload
from sqlalchemy.pool import QueuePool

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
WATI_TIMEOUT = 10

# Zoho CRM Configuration (for lead status lookup)
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in")
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")

# Global Zoho access token
zoho_access_token = None

# ============================================
# TIMEOUTS & CONFIGURATION
# ============================================

AWAITING_STATE_TIMEOUT_HOURS = 1  # Clear awaiting states after 1 hour
FLOW_STATE_TIMEOUT_HOURS = 2     # Flow considered inactive after 2 hours
FLOW_STATE_MAX_ENTRIES = 5000    # Max entries in flow state cache

# ============================================
# FLOW STATE TRACKING (Per-User Isolation)
# Each user has their own independent flow state
# ============================================

FLOW_STATE = {}  # phone -> {"triggered_at": datetime, "completed": bool, "chatbot": str}

# ============================================
# RESPONSE CACHE (Performance Optimization)
# ============================================

RESPONSE_CACHE = {}
CACHE_TTL = 60  # 60 seconds cache for analytics endpoints

def get_cached_response(cache_key: str):
    """Get cached response if still valid"""
    if cache_key in RESPONSE_CACHE:
        data, timestamp = RESPONSE_CACHE[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            return data
        else:
            del RESPONSE_CACHE[cache_key]
    return None

def set_cached_response(cache_key: str, data):
    """Cache response with timestamp"""
    RESPONSE_CACHE[cache_key] = (data, time.time())
    # Clean old cache entries if cache gets too large
    if len(RESPONSE_CACHE) > 100:
        current_time = time.time()
        keys_to_delete = [k for k, (_, ts) in RESPONSE_CACHE.items() if current_time - ts > CACHE_TTL]
        for k in keys_to_delete:
            del RESPONSE_CACHE[k]

# Messages that indicate flow is COMPLETE (end nodes from WATI chatbot)
FLOW_END_MESSAGES = [
    "thank you for reaching out. keep winning",
    "our counsellor will reach out to you within next 48 hours",
    "thank you for your valueable feedback",
    "thank you for your valuable feedback",
    "thank you for confirming",
    "has been resolved",
    "we're glad we could help",
]


def is_flow_active(phone: str) -> bool:
    """
    Check if chatbot flow is currently active for this SPECIFIC user.
    Returns True if flow was triggered but not yet completed.
    Each user is checked independently.
    """
    state = FLOW_STATE.get(phone)
    if not state:
        return False  # No flow triggered for this user
    
    # Check if flow timed out (older than FLOW_STATE_TIMEOUT_HOURS)
    triggered_at = state.get("triggered_at")
    if triggered_at:
        hours_since = (datetime.utcnow() - triggered_at).total_seconds() / 3600
        if hours_since > FLOW_STATE_TIMEOUT_HOURS:
            # Flow timed out, mark as completed
            FLOW_STATE[phone]["completed"] = True
            return False
    
    # Flow is active if triggered and not completed
    return state.get("triggered_at") is not None and not state.get("completed", False)


def mark_flow_started(phone: str, chatbot_name: str = None):
    """Mark that we triggered a chatbot flow for this SPECIFIC user"""
    FLOW_STATE[phone] = {
        "triggered_at": datetime.utcnow(),
        "completed": False,
        "chatbot": chatbot_name
    }
    
    # Cleanup old entries to prevent memory leak
    cleanup_flow_state()


def mark_flow_completed(phone: str):
    """Mark that the chatbot flow has completed for this SPECIFIC user"""
    if phone in FLOW_STATE:
        FLOW_STATE[phone]["completed"] = True
        FLOW_STATE[phone]["completed_at"] = datetime.utcnow()
    else:
        FLOW_STATE[phone] = {
            "triggered_at": None, 
            "completed": True,
            "completed_at": datetime.utcnow()
        }


def cleanup_flow_state():
    """Remove old entries from FLOW_STATE to prevent memory bloat"""
    global FLOW_STATE
    
    if len(FLOW_STATE) > FLOW_STATE_MAX_ENTRIES:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        to_remove = []
        
        for phone, state in FLOW_STATE.items():
            triggered_at = state.get("triggered_at")
            completed_at = state.get("completed_at")
            
            # Remove if both triggered and completed are old, or if only triggered is old
            check_time = completed_at or triggered_at
            if check_time and check_time < cutoff:
                to_remove.append(phone)
        
        for phone in to_remove:
            del FLOW_STATE[phone]
        
        if to_remove:
            print(f"🧹 Cleaned up {len(to_remove)} old flow state entries")


def reset_user_flow_state(phone: str):
    """Completely reset flow state for a specific user"""
    if phone in FLOW_STATE:
        del FLOW_STATE[phone]


def is_flow_end_message(message_text: str) -> bool:
    """Check if this message indicates flow completion"""
    msg_lower = message_text.lower()
    for phrase in FLOW_END_MESSAGES:
        if phrase in msg_lower:
            return True
    return False


# ============================================
# ENROLLED STATUS DEFINITIONS
# ============================================

ENROLLED_STATUSES = [
    "completed", "started", "registered",
    "mbw completed", "mbw started", "mbw registered",
    "lep completed", "lep started", "lep registered", 
    "100bm completed", "100bm started", "100bm registered",
    "mc completed", "mc started", "mc registered",
    "masterclass completed", "masterclass started", "masterclass registered",
]

def is_enrolled_status(lead_status: str) -> bool:
    """Check if lead_status indicates an enrolled participant"""
    if not lead_status:
        return False
    normalized = lead_status.strip().lower()
    for enrolled in ENROLLED_STATUSES:
        if enrolled in normalized:
            return True
    return False

# ============================================
# DUPLICATE PREVENTION CACHE (Per-Message)
# ============================================

PROCESSED_MESSAGE_IDS = set()
LAST_SENT_MESSAGES = {}  # phone -> {hash, time}
USER_CACHE = {}
USER_CACHE_TTL = 300

def is_duplicate_webhook(message_id: str) -> bool:
    """Check if we already processed this exact message ID"""
    if not message_id:
        return False
    if message_id in PROCESSED_MESSAGE_IDS:
        return True
    if len(PROCESSED_MESSAGE_IDS) > 10000:
        to_remove = list(PROCESSED_MESSAGE_IDS)[:5000]
        for item in to_remove:
            PROCESSED_MESSAGE_IDS.discard(item)
    PROCESSED_MESSAGE_IDS.add(message_id)
    return False

def can_send_message(phone: str, message: str) -> bool:
    """Prevent sending duplicate messages to same user within 60 seconds"""
    msg_hash = hashlib.md5(message.encode()).hexdigest()
    now = datetime.utcnow()
    
    if phone in LAST_SENT_MESSAGES:
        last = LAST_SENT_MESSAGES[phone]
        if last["hash"] == msg_hash:
            time_diff = (now - last["time"]).total_seconds()
            if time_diff < 60:
                return False
    
    LAST_SENT_MESSAGES[phone] = {"hash": msg_hash, "time": now}
    if len(LAST_SENT_MESSAGES) > 2000:
        LAST_SENT_MESSAGES.clear()
    return True

def get_cached_user_id(phone: str) -> Optional[int]:
    cached = USER_CACHE.get(phone)
    if cached and (datetime.utcnow() - cached["time"]).seconds < USER_CACHE_TTL:
        return cached["id"]
    return None

def cache_user(phone: str, user_id: int):
    USER_CACHE[phone] = {"id": user_id, "time": datetime.utcnow()}
    if len(USER_CACHE) > 5000:
        USER_CACHE.clear()
# ============================================
# DATABASE SETUP
# ============================================

engine = create_engine(
    DATABASE_URL, 
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_size=50,  # Increased for better concurrency
    max_overflow=100,  # Increased for peak loads
    pool_recycle=1800,
    pool_timeout=10,
    echo=False
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
# TIME PERIOD HELPER
# ============================================

def get_time_filter(time_period: str) -> Optional[datetime]:
    now = datetime.utcnow()
    
    if time_period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_period == "yesterday":
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_period == "last_7_days":
        return now - timedelta(days=7)
    elif time_period == "last_30_days":
        return now - timedelta(days=30)
    elif time_period == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif time_period == "last_month":
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month = first_of_this_month - timedelta(days=1)
        return last_month.replace(day=1)
    else:
        return None

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
    awaiting_ticket_since = Column(DateTime, nullable=True)
    needs_counsellor = Column(Boolean, default=False)
    counsellor_query = Column(Text, nullable=True)
    counsellor_requested_at = Column(DateTime, nullable=True)
    awaiting_feedback = Column(Boolean, default=False)
    awaiting_feedback_since = Column(DateTime, nullable=True)
    lead_status = Column(String(100), nullable=True)
    crm_last_sync = Column(DateTime, nullable=True)
    
    course_interests = relationship("CourseInterest", back_populates="user", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")
    queries = relationship("UserQuery", back_populates="user", cascade="all, delete-orphan")


class Ticket(Base):
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(20), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(20), default="query")
    initial_message = Column(Text, nullable=False)
    status = Column(String(20), default="pending", index=True)
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
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_name = Column(String(50), nullable=False, index=True)
    click_count = Column(Integer, default=1)
    first_clicked = Column(DateTime, default=datetime.utcnow)
    last_clicked = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="course_interests")


class UserQuery(Base):
    __tablename__ = "user_queries"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_text = Column(Text, nullable=False)
    query_type = Column(String(30), default="general")
    contact_preference = Column(String(20), default="message")
    status = Column(String(30), default="pending", index=True)
    resolved_by = Column(String(100), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="queries")

class Feedback(Base):
    __tablename__ = "feedbacks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
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
    phone_number = Column(String(20), nullable=True, index=True)
    message_id = Column(String(100), nullable=True, index=True)
    is_outgoing = Column(Boolean, default=False)
    raw_data = Column(Text)
    processed = Column(Boolean, default=False)
    action_taken = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


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
        ("users", "awaiting_ticket_since", "TIMESTAMP"),
        ("users", "needs_counsellor", "BOOLEAN DEFAULT FALSE"),
        ("users", "counsellor_query", "TEXT"),
        ("users", "counsellor_requested_at", "TIMESTAMP"),
        ("users", "awaiting_feedback", "BOOLEAN DEFAULT FALSE"),
        ("users", "awaiting_feedback_since", "TIMESTAMP"),
        ("users", "lead_status", "VARCHAR(100)"),
        ("users", "crm_last_sync", "TIMESTAMP"),
        ("webhook_logs", "message_id", "VARCHAR(100)"),
        ("webhook_logs", "is_outgoing", "BOOLEAN DEFAULT FALSE"),
        ("webhook_logs", "action_taken", "VARCHAR(100)"),
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
            
            # Add composite indexes for better query performance
            index_queries = [
                "CREATE INDEX IF NOT EXISTS idx_webhook_logs_phone_outgoing_created ON webhook_logs(phone_number, is_outgoing, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON tickets(user_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_tickets_created_status ON tickets(created_at DESC, status)",
                "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone_number)",
                "CREATE INDEX IF NOT EXISTS idx_users_participation ON users(participation_level)",
                "CREATE INDEX IF NOT EXISTS idx_users_first_seen ON users(first_seen DESC)",
                "CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_created ON ticket_messages(ticket_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_course_interests_user_course ON course_interests(user_id, course_name)",
            ]
            
            for index_query in index_queries:
                try:
                    conn.execute(text(index_query))
                except Exception as e:
                    print(f"⚠️ Index creation warning: {e}")
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
    description="Complete analytics backend with ticket system and CRM auto-routing",
    version="9.1.2",
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

# Add compression middleware for faster responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ============================================
# DATABASE DEPENDENCY
# ============================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_new_db_session():
    return SessionLocal()

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

class QueryUpdateRequest(BaseModel):
    status: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None

class MarkCounsellorDoneRequest(BaseModel):
    resolved_by: Optional[str] = "Counsellor"

# ============================================
# USER STATE MANAGEMENT (Per-User Isolation)
# ============================================

def clear_stale_user_states(db: Session, user: User) -> bool:
    """
    Clear stale awaiting states for a SPECIFIC user.
    Returns True if any state was cleared.
    This ensures one user's stale state doesn't affect their future interactions.
    """
    cleared = False
    now = datetime.utcnow()
    
    # Check if awaiting_ticket_type is stale
    if user.awaiting_ticket_type:
        awaiting_since = user.awaiting_ticket_since or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale awaiting_ticket_type for {user.phone_number} (was {user.awaiting_ticket_type}, {hours_since:.1f}h old)")
                user.awaiting_ticket_type = None
                user.awaiting_ticket_since = None
                cleared = True
    
    # Check if awaiting_feedback is stale
    if user.awaiting_feedback:
        awaiting_since = user.awaiting_feedback_since or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale awaiting_feedback for {user.phone_number} ({hours_since:.1f}h old)")
                user.awaiting_feedback = False
                user.awaiting_feedback_since = None
                cleared = True
    
    # Check if needs_counsellor without query is stale (waiting for user's query text)
    if user.needs_counsellor and not user.counsellor_query:
        awaiting_since = user.counsellor_requested_at or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale needs_counsellor for {user.phone_number} ({hours_since:.1f}h old)")
                user.needs_counsellor = False
                cleared = True
    
    if cleared:
        db.commit()
    
    return cleared


def reset_user_awaiting_states(db: Session, user: User):
    """Completely reset all awaiting states for a user"""
    user.awaiting_ticket_type = None
    user.awaiting_ticket_since = None
    user.awaiting_feedback = False
    user.awaiting_feedback_since = None
    db.commit()


def set_awaiting_ticket_type(db: Session, user: User, ticket_type: str):
    """Set awaiting ticket type with timestamp"""
    user.awaiting_ticket_type = ticket_type
    user.awaiting_ticket_since = datetime.utcnow()
    db.commit()


def set_awaiting_feedback(db: Session, user: User, awaiting: bool):
    """Set awaiting feedback with timestamp"""
    user.awaiting_feedback = awaiting
    if awaiting:
        user.awaiting_feedback_since = datetime.utcnow()
    else:
        user.awaiting_feedback_since = None
    db.commit()


# ============================================
# WEBHOOK LOG-BASED CONTEXT DETECTION (RESTORED)
# These functions check recent bot messages to detect flow context
# ============================================

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
async def wati_webhook(data: dict, background_tasks: BackgroundTasks):
    try:
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
        
        is_outgoing = (
            data.get("owner") == True or 
            data.get("isFromMe") == True or
            data.get("fromMe") == True or
            str(data.get("owner", "")).lower() == "true" or
            str(data.get("isOwner", "")).lower() == "true" or
            event_type in ["sessionMessageSent", "session_message_sent", "message_sent"]
        )
        
        if message_id and is_duplicate_webhook(message_id):
            return {"status": "duplicate"}
        
        if wa_number:
            wa_number = wa_number.replace("+", "").replace(" ", "")
        
        db = get_new_db_session()
        try:
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
            db.refresh(log)
            log_id = log.id
        finally:
            db.close()
        
        background_tasks.add_task(
            process_webhook_background,
            log_id, data, wa_number, sender_name, event_type, message_text, message_id, is_outgoing
        )
        
        return {"status": "received", "log_id": log_id}
    
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return {"status": "error", "message": str(e)[:100]}


# ============================================
# USER STATE MANAGEMENT (Per-User Isolation)
# ============================================

def clear_stale_user_states(db: Session, user: User) -> bool:
    """
    Clear stale awaiting states for a SPECIFIC user.
    Returns True if any state was cleared.
    This ensures one user's stale state doesn't affect their future interactions.
    """
    cleared = False
    now = datetime.utcnow()
    
    # Check if awaiting_ticket_type is stale
    if user.awaiting_ticket_type:
        awaiting_since = user.awaiting_ticket_since or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale awaiting_ticket_type for {user.phone_number} (was {user.awaiting_ticket_type}, {hours_since:.1f}h old)")
                user.awaiting_ticket_type = None
                user.awaiting_ticket_since = None
                cleared = True
    
    # Check if awaiting_feedback is stale
    if user.awaiting_feedback:
        awaiting_since = user.awaiting_feedback_since or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale awaiting_feedback for {user.phone_number} ({hours_since:.1f}h old)")
                user.awaiting_feedback = False
                user.awaiting_feedback_since = None
                cleared = True
    
    # Check if needs_counsellor without query is stale (waiting for user's query text)
    if user.needs_counsellor and not user.counsellor_query:
        awaiting_since = user.counsellor_requested_at or user.last_interaction
        if awaiting_since:
            hours_since = (now - awaiting_since).total_seconds() / 3600
            if hours_since > AWAITING_STATE_TIMEOUT_HOURS:
                print(f"   🧹 Clearing stale needs_counsellor for {user.phone_number} ({hours_since:.1f}h old)")
                user.needs_counsellor = False
                cleared = True
    
    if cleared:
        db.commit()
    
    return cleared


def reset_user_awaiting_states(db: Session, user: User):
    """Completely reset all awaiting states for a user"""
    user.awaiting_ticket_type = None
    user.awaiting_ticket_since = None
    user.awaiting_feedback = False
    user.awaiting_feedback_since = None
    db.commit()


def set_awaiting_ticket_type(db: Session, user: User, ticket_type: str):
    """Set awaiting ticket type with timestamp"""
    user.awaiting_ticket_type = ticket_type
    user.awaiting_ticket_since = datetime.utcnow()
    db.commit()


def set_awaiting_feedback(db: Session, user: User, awaiting: bool):
    """Set awaiting feedback with timestamp"""
    user.awaiting_feedback = awaiting
    if awaiting:
        user.awaiting_feedback_since = datetime.utcnow()
    else:
        user.awaiting_feedback_since = None
    db.commit()


# ============================================
# WEBHOOK LOG-BASED CONTEXT DETECTION (RESTORED)
# These functions check recent bot messages to detect flow context
# ============================================

def check_feedback_flow_context(db: Session, wa_number: str) -> bool:
    """
    Check if user is in feedback flow by looking at recent outgoing messages.
    This is a FALLBACK when database flag might not be set.
    """
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
                    "provide your feedback here",
                    "share your feedback"
                ]):
                    return True
                    
                if rlog.action_taken == "feedback_prompt_sent":
                    return True
                    
            except:
                pass
    
    return False


def check_counsellor_flow_context(db: Session, wa_number: str) -> bool:
    """
    Check if user is in counsellor flow by looking for the bot's prompt message.
    Flow: User clicks "Speak to counsellor" → Bot sends "Please share any queries or doubts" → User types query
    This is a FALLBACK when database flag might not be set.
    """
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
                
                # Exact phrase from WATI chatbot flow - after user clicks Yes for counsellor
                if "please share any queries or doubts you may have" in rtext:
                    return True
                
                # Also check for partial match
                if "please share any queries or doubts" in rtext:
                    return True
                    
                if rlog.action_taken == "counsellor_prompt_sent":
                    return True
                    
            except:
                pass
    
    return False


# ============================================
# ASYNC HTTP CLIENT (Connection Pooling)
# ============================================

# Create a shared async HTTP client with connection pooling
_httpx_client = None

def get_httpx_client():
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(WATI_TIMEOUT, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
    return _httpx_client

# ============================================
# WATI API FUNCTIONS (Async)
# ============================================

async def send_wati_message_async(phone_number: str, message: str) -> dict:
    """Async version of send_wati_message for better performance"""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    if not can_send_message(phone_number, message):
        print(f"⚠️ Skipping duplicate message to {phone_number}")
        return {"success": True, "skipped": True}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    from urllib.parse import quote
    url = f"{WATI_API_URL}/api/v1/sendSessionMessage/{phone}?messageText={quote(message)}"
    
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json-patch+json"
    }
    
    try:
        client = get_httpx_client()
        response = await client.post(url, headers=headers)
        result = response.json()
        
        if response.status_code == 200:
            if result.get("result") == True:
                return {"success": True, "message_id": result.get("messageId"), "response": result}
            if result.get("whatsappMessageId"):
                return {"success": True, "message_id": result.get("whatsappMessageId"), "response": result}
            if result.get("statusString") == "SENT":
                return {"success": True, "message_id": result.get("whatsappMessageId") or result.get("localMessageId"), "response": result}
            if result.get("ok") == True:
                msg_data = result.get("message", {})
                return {"success": True, "message_id": msg_data.get("whatsappMessageId") or msg_data.get("localMessageId"), "response": result}
        
        return {"success": False, "error": result.get("message") or str(result), "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_wati_message_sync(phone_number: str, message: str) -> dict:
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
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
        
        if response.status_code == 200:
            if result.get("result") == True:
                return {"success": True, "message_id": result.get("messageId"), "response": result}
            if result.get("whatsappMessageId"):
                return {"success": True, "message_id": result.get("whatsappMessageId"), "response": result}
            if result.get("statusString") == "SENT":
                return {"success": True, "message_id": result.get("whatsappMessageId") or result.get("localMessageId"), "response": result}
            if result.get("ok") == True:
                msg_data = result.get("message", {})
                return {"success": True, "message_id": msg_data.get("whatsappMessageId") or msg_data.get("localMessageId"), "response": result}
        
        return {"success": False, "error": result.get("message") or str(result), "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_wati_interactive_buttons_sync(phone_number: str, body_text: str, buttons: list) -> dict:
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
        
        if response.status_code == 200 and isinstance(result, dict):
            ok_status = result.get("ok")
            message_data = result.get("message")
            
            if ok_status == True:
                msg_id = None
                if isinstance(message_data, dict):
                    msg_id = message_data.get("whatsappMessageId") or message_data.get("localMessageId") or message_data.get("id")
                return {"success": True, "message_id": msg_id, "response": result}
            
            wamid = result.get("whatsappMessageId")
            status_str = result.get("statusString")
            result_bool = result.get("result")
            
            if wamid or status_str == "SENT" or result_bool == True:
                final_id = wamid or result.get("localMessageId") or result.get("messageId")
                return {"success": True, "message_id": final_id, "response": result}
        
        errors = result.get("errors") if isinstance(result, dict) else None
        error_msg = str(errors) if errors else "Unknown error"
        return {"success": False, "error": error_msg, "response": result}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def assign_to_operator_sync(phone_number: str, operator_email: str = "Admin@iamironlady.com") -> dict:
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/assignOperator?whatsappNumber={phone}&operatorEmail={operator_email}"
    headers = {"Authorization": f"Bearer {WATI_API_TOKEN}", "Content-Type": "application/json-patch+json"}
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        return {"success": response.status_code == 200, "response": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def unassign_operator_sync(phone_number: str) -> dict:
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI API token not configured"}
    
    phone = phone_number.replace("+", "").replace(" ", "").strip()
    url = f"{WATI_API_URL}/api/v1/unassignOperator?whatsappNumber={phone}"
    headers = {"Authorization": f"Bearer {WATI_API_TOKEN}", "Content-Type": "application/json-patch+json"}
    
    try:
        response = requests.post(url, headers=headers, timeout=WATI_TIMEOUT)
        return {"success": response.status_code == 200, "response": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_wati_message(phone_number: str, message: str) -> dict:
    return send_wati_message_sync(phone_number, message)

def send_wati_interactive_buttons(phone_number: str, body_text: str, buttons: list) -> dict:
    return send_wati_interactive_buttons_sync(phone_number, body_text, buttons)

def assign_to_operator(phone_number: str, operator_email: str = "Admin@iamironlady.com") -> dict:
    return assign_to_operator_sync(phone_number, operator_email)

def unassign_operator(phone_number: str) -> dict:
    return unassign_operator_sync(phone_number)


def send_wati_interactive_buttons_with_reply(phone_number: str, body_text: str, buttons: list, reply_to_message_id: str = None) -> dict:
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
    
    if reply_to_message_id:
        payload["replyToMessageId"] = reply_to_message_id
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=WATI_TIMEOUT)
        result = response.json()
        
        if response.status_code == 200 and isinstance(result, dict):
            ok_status = result.get("ok")
            message_data = result.get("message")
            
            if ok_status == True:
                msg_id = None
                if isinstance(message_data, dict):
                    msg_id = message_data.get("whatsappMessageId") or message_data.get("localMessageId") or message_data.get("id")
                return {"success": True, "message_id": msg_id, "response": result}
            
            wamid = result.get("whatsappMessageId")
            status_str = result.get("statusString")
            result_bool = result.get("result")
            
            if wamid or status_str == "SENT" or result_bool == True:
                final_id = wamid or result.get("localMessageId") or result.get("messageId")
                return {"success": True, "message_id": final_id, "response": result}
        
        errors = result.get("errors") if isinstance(result, dict) else None
        error_msg = str(errors) if errors else "Unknown error"
        return {"success": False, "error": error_msg, "response": result}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def trigger_wati_chatbot(phone_number: str, chatbot_name: str) -> bool:
    """
    Trigger WATI chatbot by sending Interactive Button with keyword.
    User clicks button → WATI keyword action triggers → Chatbot starts
    
    ENROLLED → Send "Enrolled Participant" button → Triggers 03_Enrolled_Support_Complete chatbot
    NEW → Send "New to Platform" button → Triggers 02_New_User_Complete chatbot
    """
    if not WATI_API_TOKEN:
        print("      ❌ WATI API token not configured", flush=True)
        return False

    phone = phone_number.replace("+", "").replace(" ", "").replace("-", "").strip()
    headers = {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Map chatbot names to keyword button text
    chatbot_keywords = {
        "03_Enrolled_Support_Complete": "Enrolled Participant",
        "02_New_User_Complete": "New to Platform",
    }
    
    button_text = chatbot_keywords.get(chatbot_name, chatbot_name)
    
    url = f"{WATI_API_URL}/api/v1/sendInteractiveButtonsMessage?whatsappNumber={phone}"
    
    payload = {
        "body": "Please choose your participation level below.",
        "buttons": [{"text": button_text}]
    }
    
    try:
        print(f"      🔄 Sending button: '{button_text}'", flush=True)
        resp = requests.post(url, headers=headers, json=payload, timeout=WATI_TIMEOUT)
        
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        
        print(f"      📡 Response: {resp.status_code}", flush=True)
        
        if resp.status_code == 200 and isinstance(body, dict):
            if body.get("result") == True or body.get("ok") == True:
                print(f"      ✅ Button sent successfully!", flush=True)
                return True
            elif body.get("result") == False:
                print(f"      ❌ API error: {body.get('info', 'Unknown')}", flush=True)
                return False
        
        print(f"      ❌ Failed to send button", flush=True)
        return False
        
    except Exception as e:
        print(f"      ❌ Error: {e}", flush=True)
        return False


# ============================================
# ZOHO CRM INTEGRATION
# ============================================

def refresh_zoho_token() -> bool:
    global zoho_access_token

    if not (ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN):
        return False

    url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token"
    params = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }

    try:
        resp = requests.post(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            zoho_access_token = data.get("access_token")
            return True
        else:
            print(f"      ❌ Zoho token refresh failed: {resp.text}")
            return False
    except Exception as e:
        print(f"      ❌ Zoho token refresh exception: {e}")
        return False


def search_lead_by_phone(phone_number: str) -> Optional[dict]:
    """Search for lead in Zoho CRM by phone number - INDEPENDENT per search"""
    global zoho_access_token

    if not zoho_access_token:
        if not refresh_zoho_token():
            return None

    headers = {"Authorization": f"Zoho-oauthtoken {zoho_access_token}"}
    phone_clean = phone_number.replace("+", "").replace(" ", "").replace("-", "").strip()

    search_variants = [phone_clean]
    if phone_clean.startswith("91") and len(phone_clean) == 12:
        search_variants.append("+" + phone_clean)
        search_variants.append(phone_clean[2:])
    elif len(phone_clean) == 10:
        search_variants.append("+91" + phone_clean)
        search_variants.append("91" + phone_clean)

    all_leads = []
    search_url = f"{ZOHO_API_DOMAIN}/crm/v5/Leads/search"

    for variant in search_variants:
        try:
            params = {"phone": variant}
            response = requests.get(search_url, headers=headers, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    all_leads.extend(data["data"])
            elif response.status_code == 401:
                if refresh_zoho_token():
                    headers["Authorization"] = f"Zoho-oauthtoken {zoho_access_token}"
                    response = requests.get(search_url, headers=headers, params=params, timeout=15)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("data"):
                            all_leads.extend(data["data"])
        except Exception:
            pass

    if not all_leads:
        return None

    seen_ids = set()
    unique_leads = []
    for lead in all_leads:
        lead_id = lead.get("id")
        if lead_id and lead_id not in seen_ids:
            seen_ids.add(lead_id)
            unique_leads.append(lead)

    def get_lead_score(lead):
        status = lead.get("Lead_Status") or ""
        source = lead.get("Lead_Source") or ""
        
        status_priority = {
            "MBW Completed": 1, "MC Completed": 1, "100BM Completed": 1, "LEP Completed": 1, "Completed": 1,
            "MBW Started": 2, "MC Started": 2, "100BM Started": 2, "LEP Started": 2, "Started": 2,
            "MBW Registered": 3, "MC Registered": 3, "Registered": 3,
            "Hot": 10, "Warm": 20, "Cold": 30, "New": 90
        }
        
        source_priority = {
            "Organic": 1, "Organic - Website": 1,
            "Online - Meta Ads": 2, "Meta": 2,
            "Online - Google Ads": 3, "Google": 3,
            "Online": 5, "Referral": 5,
            "Chat": 90, "WATI": 95
        }
        
        s_priority = 100
        for key, val in status_priority.items():
            if key.lower() in status.lower():
                s_priority = min(s_priority, val)
                break
        
        src_priority = 50
        for key, val in source_priority.items():
            if key.lower() in source.lower():
                src_priority = min(src_priority, val)
                break
        
        if not status or status.lower() == "none":
            s_priority = 999
        
        return (s_priority, src_priority)

    unique_leads.sort(key=get_lead_score)

    for lead in unique_leads:
        if lead.get("Lead_Status"):
            return lead

    return unique_leads[0] if unique_leads else None


def get_lead_status_from_crm(db: Session, user: User, phone_number: str) -> Optional[str]:
    """
    Get lead status from CRM for a SPECIFIC user.
    Each user's CRM lookup is completely independent.
    """
    if not (ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN):
        return None

    now = datetime.utcnow()

    # Use cached status if recent (within 24 hours)
    if user.lead_status is not None and user.crm_last_sync:
        if now - user.crm_last_sync < timedelta(hours=24):
            return user.lead_status

    # Fresh CRM lookup for this specific user
    lead = search_lead_by_phone(phone_number)
    
    if lead:
        lead_status = lead.get("Lead_Status")
        lead_name = lead.get("Full_Name")
        lead_email = lead.get("Email")

        user.lead_status = lead_status if lead_status else "New"

        if lead_email and not user.email:
            user.email = lead_email
        if lead_name and (not user.name or user.name == "Unknown"):
            user.name = lead_name
    else:
        user.lead_status = "New"

    user.crm_last_sync = now
    db.commit()
    db.refresh(user)
    return user.lead_status


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
    """Get or create user - each user has independent state"""
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
    
    cache_user(phone_number, user.id)
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


def update_course_interest(db: Session, user_id: int, course_name: str):
    interest = db.query(CourseInterest).filter(
        CourseInterest.user_id == user_id,
        CourseInterest.course_name == course_name
    ).first()
    
    if interest:
        interest.click_count += 1
        interest.last_clicked = datetime.utcnow()
    else:
        interest = CourseInterest(user_id=user_id, course_name=course_name)
        db.add(interest)
    db.commit()


def add_enrolled_program(user: User, program: str):
    if not user.enrolled_program:
        user.enrolled_program = program
    elif program not in user.enrolled_program:
        user.enrolled_program = f"{user.enrolled_program},{program}"


def extract_email(text: str) -> Optional[str]:
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, text)
    return match.group() if match else None


# ============================================
# MESSAGE TYPE DETECTION (RESTORED specific types)
# ============================================

QUERY_BUTTONS = ["i have a query", "have a query", "query"]
CONCERN_BUTTONS = ["raise a concern", "have a concern", "concern"]
SATISFACTION_YES = ["yes, resolved", "yes,resolved"]
SATISFACTION_NO = ["need more help", "needmorehelp"]

# Chatbot navigation buttons - NOT including speak_to_counsellor and provide_feedback
CHATBOT_BUTTONS = [
    "new to platform", "enrolled participant", "more options",
    "please choose your participation", "ask a question here",
    "lep", "100bm", "mbw", "masterclass", "know more", 
    "know about programs", "leadership essential", "100 board members", 
    "mbw(warfare)", "yes", "no"
]

IGNORE_MESSAGES = [
    "hi", "hello", "hey", "ok", "okay", "thanks", "thank you",
    "bye", "good morning", "good night", "hmm"
]


def get_message_type(message: str) -> str:
    """Classify message type - independent of user state"""
    msg = message.lower().strip()
    
    if msg in SATISFACTION_YES or "yes, resolved" in msg:
        return "satisfaction_yes"
    if msg in SATISFACTION_NO or "need more help" in msg:
        return "satisfaction_no"
    
    for btn in QUERY_BUTTONS:
        if btn in msg:
            return "query_button"
    for btn in CONCERN_BUTTONS:
        if btn in msg:
            return "concern_button"
    
    # RESTORED: Specific handlers for speak_to_counsellor and provide_feedback
    if "speak to counsellor" in msg:
        return "speak_to_counsellor"
    
    if "provide feedback" in msg:
        return "provide_feedback"
    
    # All other chatbot buttons - let WATI handle
    for cb in CHATBOT_BUTTONS:
        if cb in msg:
            return "chatbot_button"
    
    if msg in IGNORE_MESSAGES or len(msg) < 3:
        return "ignore"
    
    return "free_text"


# ============================================
# BACKGROUND PROCESSING (Per-User Isolation)
# ============================================

def process_webhook_background(
    log_id: int,
    data: dict,
    wa_number: str,
    sender_name: Optional[str],
    event_type: str,
    message_text: str,
    message_id: str,
    is_outgoing: bool
):
    """
    Background task to process webhook - with CRM auto-routing (v9.1.2)
    FIXED: Feedback and Counsellor query capture now work correctly.
    """
    db = get_new_db_session()
    
    try:
        message_lower = message_text.lower()
        
        log = db.query(WebhookLog).filter(WebhookLog.id == log_id).first()
        if not log:
            return
        
        # ========================================
        # SKIP BROADCAST STATUS EVENTS
        # ========================================
        
        if event_type in ["templateMessageFailed", "sentMessageDELIVERED", "sentMessageREAD", 
                         "delivered", "read", "failed", "templateMessageSent_v2"]:
            log.action_taken = f"{event_type}_skipped"
            log.processed = True
            db.commit()
            return
        
        if not wa_number:
            log.action_taken = "no_phone"
            log.processed = True
            db.commit()
            return
        
        # ========================================
        # GET USER (Each user is independent)
        # ========================================
        
        user = get_or_create_user(db, wa_number, name=sender_name)
        
        # ========================================
        # CLEAR STALE STATES FOR THIS USER
        # ========================================
        
        stale_cleared = clear_stale_user_states(db, user)
        
        # ========================================
        # OUTGOING BOT MESSAGES
        # ========================================
        
        if is_outgoing and message_text:
            # Check if this is a flow END message for THIS user
            if is_flow_end_message(message_text):
                mark_flow_completed(wa_number)
                print(f"   ✅ Flow COMPLETED for {wa_number}: {message_text[:50]}...", flush=True)
            
            # Enrollment tracking
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
                log.action_taken = "enrolled"
                log.processed = True
                db.commit()
                return
            
            # Course interest tracking
            if "leadership essentials program enables you to master" in message_lower:
                update_course_interest(db, user.id, "LEP")
                log.action_taken = "course_LEP"
            elif "100 board members program enables you to focus" in message_lower:
                update_course_interest(db, user.id, "100BM")
                log.action_taken = "course_100BM"
            elif "master of business warfare focuses on winning" in message_lower:
                update_course_interest(db, user.id, "MBW")
                log.action_taken = "course_MBW"
            elif "iron lady leadership masterclass helps you" in message_lower:
                update_course_interest(db, user.id, "Masterclass")
                log.action_taken = "course_Masterclass"
            
            # Participation level
            if "welcome to the iron lady platform" in message_lower:
                user.participation_level = "New to platform"
                db.commit()
                log.action_taken = "participation_new"
            elif "ask a question here" in message_lower:
                user.participation_level = "Enrolled Participant"
                db.commit()
                log.action_taken = "participation_enrolled"
            
            # Feedback prompt
            if "please provide your feedback here" in message_lower or "provide your feedback here" in message_lower:
                set_awaiting_feedback(db, user, True)
                log.action_taken = "feedback_prompt_sent"
            
            # Counsellor prompt - set needs_counsellor = True, waiting for user's query
            if "please share any queries or doubts you may have" in message_lower:
                user.needs_counsellor = True
                user.counsellor_requested_at = datetime.utcnow()
                db.commit()
                log.action_taken = "counsellor_prompt_sent"
            
            # Feedback confirmation
            if "thank you for your valueable feedback" in message_lower or "thank you for your valuable feedback" in message_lower:
                set_awaiting_feedback(db, user, False)
                log.action_taken = "feedback_confirmed"
            
            if not log.action_taken:
                log.action_taken = "bot_message"
            log.processed = True
            db.commit()
            return
        
        # ========================================
        # INCOMING MESSAGES
        # ========================================
        
        if not message_text:
            log.action_taken = "no_text"
            log.processed = True
            db.commit()
            return
        
        msg_type = get_message_type(message_text)
        
        # ========================================
        # PRIORITY 1: FEEDBACK CAPTURE (BEFORE CRM routing!)
        # Check BOTH database flag AND webhook logs as fallback
        # ========================================
        
        is_in_feedback_flow = user.awaiting_feedback or check_feedback_flow_context(db, wa_number)
        
        if is_in_feedback_flow and msg_type == "free_text":
            # Prevent duplicate feedback within 5 minutes
            five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
            recent_feedback = db.query(Feedback).filter(
                Feedback.user_id == user.id,
                Feedback.created_at >= five_mins_ago
            ).first()
            
            if not recent_feedback:
                feedback = Feedback(user_id=user.id, feedback_text=message_text)
                db.add(feedback)
                set_awaiting_feedback(db, user, False)
                print(f"✅ Feedback captured for {wa_number}: {message_text[:50]}...", flush=True)
                log.action_taken = "feedback_captured"
                log.processed = True
                db.commit()
                return
            else:
                print(f"⚠️ Duplicate feedback prevented for {wa_number}", flush=True)
        
        # ========================================
        # PRIORITY 2: COUNSELLOR QUERY CAPTURE (BEFORE CRM routing!)
        # Check BOTH database flag AND webhook logs as fallback
        # ========================================
        
        is_in_counsellor_flow = (user.needs_counsellor and not user.counsellor_query) or check_counsellor_flow_context(db, wa_number)
        
        if is_in_counsellor_flow and msg_type == "free_text":
            # Only capture if we don't already have a query
            if not user.counsellor_query:
                user.counsellor_query = message_text
                user.counsellor_requested_at = datetime.utcnow()
                user.needs_counsellor = True
                db.commit()
                
                print(f"   📞 Counsellor query captured for {wa_number}: {message_text[:50]}...", flush=True)
                
                # Optionally assign to operator for follow-up
                assign_to_operator_sync(wa_number)
                
                log.action_taken = "counsellor_query_captured"
                log.processed = True
                db.commit()
                return
        
        # ========================================
        # PRIORITY 3: "Speak to Counsellor" button click
        # ========================================
        
        if msg_type == "speak_to_counsellor":
            # Mark that user wants counsellor, waiting for their query
            user.needs_counsellor = True
            user.counsellor_requested_at = datetime.utcnow()
            db.commit()
            log.action_taken = "speak_to_counsellor_clicked"
            log.processed = True
            db.commit()
            return
        
        # ========================================
        # PRIORITY 4: "Provide Feedback" button click
        # ========================================
        
        if msg_type == "provide_feedback":
            set_awaiting_feedback(db, user, True)
            log.action_taken = "provide_feedback_clicked"
            log.processed = True
            db.commit()
            return
        
        # ========================================
        # CRM AUTO-ROUTING DECISION (Per-User)
        # NOW comes AFTER feedback and counsellor capture
        # ========================================
        
        is_button = msg_type in ["query_button", "concern_button", "satisfaction_yes", 
                                 "satisfaction_no", "chatbot_button"]
        
        is_awaiting_input = user.awaiting_ticket_type in ["query", "concern"]
        
        flow_active = is_flow_active(wa_number)
        
        should_skip = is_button or is_awaiting_input or flow_active
        
        print(flush=True)
        print("=" * 70, flush=True)
        print(f"📱 INCOMING: {wa_number}", flush=True)
        print(f"   Message: \"{message_text[:50]}{'...' if len(message_text) > 50 else ''}\"", flush=True)
        print(f"   Type: {msg_type}", flush=True)
        print(f"   Is Button: {is_button}", flush=True)
        print(f"   Awaiting Input: {is_awaiting_input} (ticket_type={user.awaiting_ticket_type})", flush=True)
        print(f"   Flow Active: {flow_active}", flush=True)
        if stale_cleared:
            print(f"   ⚠️ Stale state was cleared", flush=True)
        print(f"   → Skip Auto-Route: {should_skip}", flush=True)
        
        # ========================================
        # TRIGGER WATI CHATBOT IF NEEDED (Per-User)
        # ========================================
        
        if not should_skip and msg_type == "free_text":
            if ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN:
                lead_status = get_lead_status_from_crm(db, user, wa_number)
                is_enrolled = is_enrolled_status(lead_status)
                participation = "ENROLLED" if is_enrolled else "NEW"
                target_chatbot = "03_Enrolled_Support_Complete" if is_enrolled else "02_New_User_Complete"
                
                print(f"   📊 CRM Status: {lead_status} → {participation}", flush=True)
                print(f"   🎯 Triggering: {target_chatbot}", flush=True)
                
                success = trigger_wati_chatbot(wa_number, target_chatbot)
                
                if success:
                    mark_flow_started(wa_number, target_chatbot)
                    print(f"   ✅ CHATBOT TRIGGERED - Flow marked ACTIVE for {wa_number}", flush=True)
                    log.action_taken = f"auto_route:{participation}|{target_chatbot}"
                else:
                    print(f"   ❌ CHATBOT TRIGGER FAILED for {wa_number}", flush=True)
                    log.action_taken = f"auto_route_failed:{target_chatbot}"
                
                print("=" * 70, flush=True)
                log.processed = True
                db.commit()
                return
            else:
                print(f"   ⚠️ Zoho CRM not configured", flush=True)
        
        # Handle "ignore" type messages that aren't buttons
        if msg_type == "ignore" and not is_awaiting_input and not flow_active:
            if ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN:
                lead_status = get_lead_status_from_crm(db, user, wa_number)
                is_enrolled = is_enrolled_status(lead_status)
                participation = "ENROLLED" if is_enrolled else "NEW"
                target_chatbot = "03_Enrolled_Support_Complete" if is_enrolled else "02_New_User_Complete"
                
                print(f"   📊 CRM Status: {lead_status} → {participation}", flush=True)
                print(f"   🎯 Triggering (greeting): {target_chatbot}", flush=True)
                
                success = trigger_wati_chatbot(wa_number, target_chatbot)
                
                if success:
                    mark_flow_started(wa_number, target_chatbot)
                    print(f"   ✅ CHATBOT TRIGGERED - Flow marked ACTIVE for {wa_number}", flush=True)
                    log.action_taken = f"greeting_route:{participation}|{target_chatbot}"
                else:
                    log.action_taken = f"greeting_route_failed:{target_chatbot}"
                
                print("=" * 70, flush=True)
                log.processed = True
                db.commit()
                return
        
        print("=" * 70, flush=True)
        
        # ========================================
        # NORMAL MESSAGE PROCESSING (Per-User)
        # ========================================
        
        active_ticket = get_active_ticket(db, wa_number)
        
        # Query button
        if msg_type == "query_button":
            set_awaiting_ticket_type(db, user, "query")
            log.action_taken = "awaiting_query"
            log.processed = True
            db.commit()
            return
        
        # Concern button
        if msg_type == "concern_button":
            set_awaiting_ticket_type(db, user, "concern")
            log.action_taken = "awaiting_concern"
            log.processed = True
            db.commit()
            return
        
        # Chatbot button - let WATI handle, just log
        if msg_type == "chatbot_button":
            log.action_taken = "chatbot_button"
            log.processed = True
            db.commit()
            return
        
        # Ignore casual messages when not in ticket flow
        if msg_type == "ignore" and not active_ticket:
            log.action_taken = "ignored"
            log.processed = True
            db.commit()
            return
        
        # Create ticket if awaiting for THIS user
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
            
            # Clear awaiting state for THIS user
            user.awaiting_ticket_type = None
            user.awaiting_ticket_since = None
            user.has_active_ticket = True
            db.commit()
            
            assign_to_operator_sync(wa_number)
            
            msg = f"✅ Your ticket {ticket_number} has been created for this {category}.\n\nOur counsellor will reach out to you within the next 24 hours.\n\nThank you for your patience!"
            send_wati_message_sync(wa_number, msg)
            
            log.action_taken = f"created_{ticket_number}"
            log.processed = True
            db.commit()
            return
        
        # Satisfaction YES
        if active_ticket and msg_type == "satisfaction_yes":
            active_ticket.status = "resolved"
            active_ticket.resolved_at = datetime.utcnow()
            user.has_active_ticket = False
            db.commit()
            
            send_wati_message_sync(wa_number, f"Thank you for confirming! Your ticket {active_ticket.ticket_number} has been resolved.\n\nWe're glad we could help!")
            unassign_operator_sync(wa_number)
            
            log.action_taken = f"resolved_{active_ticket.ticket_number}"
            log.processed = True
            db.commit()
            return
        
        # Satisfaction NO
        if active_ticket and msg_type == "satisfaction_no":
            if active_ticket.status != "awaiting":
                active_ticket.status = "awaiting"
                active_ticket.last_user_message_at = datetime.utcnow()
                db.commit()
                
                db.add(TicketMessage(
                    ticket_id=active_ticket.id,
                    direction="incoming",
                    message_type="text",
                    message_text="[User clicked: Need More Help]",
                    wati_message_id=message_id
                ))
                db.commit()
            
            log.action_taken = f"need_more_help_{active_ticket.ticket_number}"
            log.processed = True
            db.commit()
            return
        
        # Active ticket follow-up
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
            
            if active_ticket.status == "awaiting":
                active_ticket.status = "pending"
                db.commit()
                send_wati_message_sync(wa_number, f"Your ticket {active_ticket.ticket_number} is still in progress. Our counsellor will reach you within 24 hours.")
                log.action_taken = f"followup_{active_ticket.ticket_number}"
            else:
                db.commit()
                log.action_taken = f"silent_{active_ticket.ticket_number}"
            
            log.processed = True
            db.commit()
            return
        
        # Email capture
        email = extract_email(message_text)
        if email:
            user.email = email
            db.commit()
            log.action_taken = "email_captured"
            log.processed = True
            db.commit()
            return
        
        # ----------------------------------------
        # DEFAULT: Just log
        # ----------------------------------------
        log.action_taken = "logged"
        log.processed = True
        db.commit()
        return
    
    except Exception as e:
        print(f"❌ Background processing error for {wa_number}: {e}")
        import traceback
        traceback.print_exc()
        try:
            log = db.query(WebhookLog).filter(WebhookLog.id == log_id).first()
            if log:
                log.action_taken = f"error:{str(e)[:50]}"
                log.processed = False
                db.commit()
        except:
            pass
    finally:
        db.close()


# ============================================
# ROOT & HEALTH
# ============================================

@app.get("/")
async def root():
    return {
        "name": "Iron Lady WATI Analytics",
        "version": "9.1.2",
        "status": "running",
        "crm_auto_routing": True,
        "user_isolation": True,
        "fixes": [
            "feedback_capture_fixed",
            "counsellor_query_capture_fixed",
            "course_interest_users_endpoint_added"
        ]
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        zoho_configured = bool(ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN)
        
        return {
            "status": "healthy",
            "database": "connected",
            "users": db.query(User).count(),
            "tickets": db.query(Ticket).count(),
            "pending_tickets": db.query(Ticket).filter(Ticket.status == "pending").count(),
            "feedbacks": db.query(Feedback).count(),
            "needs_counsellor": db.query(User).filter(User.needs_counsellor == True).count(),
            "wati": bool(WATI_API_TOKEN),
            "zoho_crm": zoho_configured,
            "flow_state_entries": len(FLOW_STATE),
            "version": "9.1.2"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ============================================
# TICKET ENDPOINTS
# ============================================

@app.get("/api/tickets")
async def get_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    time_period: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),  # Reduced default limit, max 200
    db: Session = Depends(get_db)
):
    # Use eager loading to avoid N+1 queries
    query = db.query(Ticket).options(joinedload(Ticket.user))
    
    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)
    
    time_filter = get_time_filter(time_period)
    if time_filter:
        query = query.filter(Ticket.created_at >= time_filter)
    
    # Get total count for pagination
    total_count = query.count()
    
    tickets = query.order_by(Ticket.created_at.desc()).offset(skip).limit(limit).all()
    
    # Batch fetch all message counts in ONE query instead of N queries
    ticket_ids = [t.id for t in tickets]
    message_counts = {}
    if ticket_ids:
        counts = db.query(
            TicketMessage.ticket_id,
            func.count(TicketMessage.id).label('count')
        ).filter(TicketMessage.ticket_id.in_(ticket_ids)).group_by(TicketMessage.ticket_id).all()
        message_counts = {ticket_id: count for ticket_id, count in counts}
    
    result = []
    for t in tickets:
        last_msg = t.last_user_message_at or t.created_at
        hours_left = max(0, 24 - (datetime.utcnow() - last_msg).total_seconds() / 3600)
        msg_count = message_counts.get(t.id, 0)
        
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
    
    # Optimize stats: Get all stats in ONE query using conditional aggregation
    base_query = db.query(Ticket)
    if time_filter:
        base_query = base_query.filter(Ticket.created_at >= time_filter)
    
    stats_query = base_query.with_entities(
        func.count(Ticket.id).label('total'),
        func.sum(case((Ticket.status == "pending", 1), else_=0)).label('pending'),
        func.sum(case((Ticket.status == "in_progress", 1), else_=0)).label('in_progress'),
        func.sum(case((Ticket.status == "resolved", 1), else_=0)).label('resolved'),
        func.sum(case((Ticket.category == "query", 1), else_=0)).label('queries'),
        func.sum(case((Ticket.category == "concern", 1), else_=0)).label('concerns')
    ).first()
    
    return {
        "tickets": result,
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + limit) < total_count,
        "stats": {
            "total": stats_query.total or 0,
            "pending": int(stats_query.pending or 0),
            "in_progress": int(stats_query.in_progress or 0),
            "resolved": int(stats_query.resolved or 0),
            "queries": int(stats_query.queries or 0),
            "concerns": int(stats_query.concerns or 0)
        }
    }


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    # Eagerly load user and messages in ONE query
    ticket = db.query(Ticket).options(
        joinedload(Ticket.user),
        selectinload(Ticket.messages)
    ).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Use already loaded messages, sorted
    messages = sorted(ticket.messages, key=lambda m: m.created_at)
    
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
    # Eagerly load user to avoid extra query
    ticket = db.query(Ticket).options(joinedload(Ticket.user)).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status == "resolved":
        raise HTTPException(status_code=400, detail="Ticket already resolved")
    
    last_msg = ticket.last_user_message_at or ticket.created_at
    hours_since = (datetime.utcnow() - last_msg).total_seconds() / 3600
    
    if hours_since > 24:
        raise HTTPException(status_code=400, detail="24-hour window expired")
    
    phone = ticket.user.phone_number
    
    # Get the FIRST incoming message (the original query/concern that created the ticket)
    # This will be quoted in WhatsApp-style reply so user knows which query/concern is being answered
    first_user_msg = db.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id,
        TicketMessage.direction == "incoming",
        TicketMessage.wati_message_id != None
    ).order_by(TicketMessage.created_at.asc()).first()  # Get FIRST message (ascending order)
    
    reply_to_message_id = first_user_msg.wati_message_id if first_user_msg else None
    
    full_msg = f"{reply.message}\n\n───────────────────\nAre you satisfied with this response?"
    buttons = [{"text": "Yes, Resolved"}, {"text": "Need More Help"}]
    
    result = send_wati_interactive_buttons_with_reply(phone, full_msg, buttons, reply_to_message_id)
    
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
    
    db.commit()
    return {"success": True, "status": update.status}


# ============================================
# USER ENDPOINTS
# ============================================

@app.get("/api/users")
async def get_all_users(
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),  # Reduced default limit, max 200
    participation_level: Optional[str] = None,
    time_period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    # Use eager loading to avoid N+1 queries - load relationships upfront
    query = db.query(User).options(
        selectinload(User.course_interests),
        selectinload(User.feedbacks)
    )
    
    if participation_level and participation_level != "All":
        query = query.filter(User.participation_level == participation_level)
    
    time_filter = get_time_filter(time_period)
    if time_filter:
        query = query.filter(User.first_seen >= time_filter)
    
    # Get total count for pagination
    total_count = query.count()
    
    users = query.order_by(User.last_interaction.desc()).offset(skip).limit(limit).all()
    
    result = []
    for user in users:
        # Use already loaded relationships instead of querying
        course_list = list(set([ci.course_name for ci in user.course_interests]))
        
        # Get latest feedback from already loaded feedbacks
        latest_feedback = max(user.feedbacks, key=lambda f: f.created_at) if user.feedbacks else None
        
        result.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "has_active_ticket": user.has_active_ticket,
            "needs_counsellor": user.needs_counsellor or False,
            "counsellor_query": user.counsellor_query,
            "counsellor_requested_at": convert_to_ist(user.counsellor_requested_at),
            "course_interests": course_list,
            "feedback": latest_feedback.feedback_text if latest_feedback else None,
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction),
            "lead_status": user.lead_status
        })
    
    return {
        "users": result, 
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + limit) < total_count
    }


@app.get("/api/users/{user_id}")
async def get_user_details(user_id: int, db: Session = Depends(get_db)):
    # Eagerly load all relationships in ONE query instead of 4 separate queries
    user = db.query(User).options(
        selectinload(User.course_interests),
        selectinload(User.queries),
        selectinload(User.feedbacks),
        selectinload(User.tickets)
    ).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Use already loaded relationships
    course_interests = sorted(user.course_interests, key=lambda ci: ci.last_clicked, reverse=True)
    queries = sorted(user.queries, key=lambda q: q.created_at, reverse=True)
    feedbacks = sorted(user.feedbacks, key=lambda f: f.created_at, reverse=True)
    tickets = sorted(user.tickets, key=lambda t: t.created_at, reverse=True)
    
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "participation_level": user.participation_level,
            "enrolled_program": user.enrolled_program,
            "has_active_ticket": user.has_active_ticket,
            "needs_counsellor": user.needs_counsellor or False,
            "counsellor_query": user.counsellor_query,
            "counsellor_requested_at": convert_to_ist(user.counsellor_requested_at),
            "first_seen": convert_to_ist(user.first_seen),
            "last_interaction": convert_to_ist(user.last_interaction),
            "lead_status": user.lead_status
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
                "status": q.status,
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
        ],
        "tickets": [
            {
                "id": t.id,
                "ticket_number": t.ticket_number,
                "category": t.category,
                "status": t.status,
                "created_at": convert_to_ist(t.created_at)
            }
            for t in tickets
        ]
    }


@app.patch("/api/users/{user_id}/counsellor-done")
async def mark_counsellor_done(user_id: int, request: MarkCounsellorDoneRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.needs_counsellor = False
    user.counsellor_query = None
    user.counsellor_requested_at = None
    db.commit()
    
    return {"success": True, "user_id": user_id}


# ============================================
# COURSE INTEREST ENDPOINTS (FIXED - Added missing endpoint)
# ============================================

@app.get("/api/course-interests")
async def get_course_interests_summary(
    time_period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    courses = ["LEP", "100BM", "MBW", "Masterclass"]
    
    result = []
    for course in courses:
        query = db.query(CourseInterest).filter(CourseInterest.course_name == course)
        
        time_filter = get_time_filter(time_period)
        if time_filter:
            query = query.filter(CourseInterest.first_clicked >= time_filter)
        
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(
            CourseInterest.course_name == course
        ).scalar() or 0
        
        if time_filter:
            total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(
                CourseInterest.course_name == course,
                CourseInterest.first_clicked >= time_filter
            ).scalar() or 0
        
        unique_users = query.count()
        
        result.append({
            "course_name": course,
            "total_clicks": int(total_clicks),
            "unique_users": unique_users
        })
    
    return {"course_interests": result}


@app.get("/api/course-interests/{course_name}")
async def get_course_interest_users(
    course_name: str,
    time_period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    RESTORED ENDPOINT: Get all users interested in a specific course.
    Returns users sorted by click_count (highest interest first).
    """
    # Use eager loading to avoid N+1 queries
    query = db.query(CourseInterest).options(joinedload(CourseInterest.user)).filter(CourseInterest.course_name == course_name)
    
    time_filter = get_time_filter(time_period)
    if time_filter:
        query = query.filter(CourseInterest.first_clicked >= time_filter)
    
    # Sort by click_count descending to show highest interest first
    interests = query.order_by(CourseInterest.click_count.desc()).all()
    
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
    time_period: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    # Use eager loading to avoid N+1 queries
    query = db.query(Feedback).options(joinedload(Feedback.user))
    
    time_filter = get_time_filter(time_period)
    if time_filter:
        query = query.filter(Feedback.created_at >= time_filter)
    
    feedbacks = query.order_by(Feedback.created_at.desc()).offset(skip).limit(limit).all()
    
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
# QUERY ENDPOINTS (RESTORED)
# ============================================

@app.get("/api/queries")
async def get_all_queries(
    status: Optional[str] = None,
    contact_preference: Optional[str] = None,
    time_period: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """RESTORED ENDPOINT: Get all user queries with filtering"""
    # Use eager loading to avoid N+1 queries
    query = db.query(UserQuery).options(joinedload(UserQuery.user))
    
    if status:
        query = query.filter(UserQuery.status == status)
    if contact_preference:
        query = query.filter(UserQuery.contact_preference == contact_preference)
    
    time_filter = get_time_filter(time_period)
    if time_filter:
        query = query.filter(UserQuery.created_at >= time_filter)
    
    queries = query.order_by(UserQuery.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for q in queries:
        result.append({
            "id": q.id,
            "user_id": q.user_id,
            "user_name": q.user.name,
            "user_phone": q.user.phone_number,
            "query_text": q.query_text,
            "query_type": q.query_type,
            "contact_preference": q.contact_preference,
            "status": q.status,
            "resolved_by": q.resolved_by,
            "created_at": convert_to_ist(q.created_at)
        })
    
    base_query = db.query(UserQuery)
    if time_filter:
        base_query = base_query.filter(UserQuery.created_at >= time_filter)
    
    return {
        "queries": result,
        "total": base_query.count(),
        "pending": base_query.filter(UserQuery.status == "pending").count()
    }


@app.patch("/api/queries/{query_id}")
async def update_query_status(query_id: int, update: QueryUpdateRequest, db: Session = Depends(get_db)):
    """RESTORED ENDPOINT: Update query status"""
    query = db.query(UserQuery).filter(UserQuery.id == query_id).first()
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    query.status = update.status
    if update.resolved_by:
        query.resolved_by = update.resolved_by
    if update.resolution_notes:
        query.resolution_notes = update.resolution_notes
    
    db.commit()
    return {"status": "success", "query_id": query_id, "new_status": update.status}


# ============================================
# ANALYTICS SUMMARY (RESTORED full data)
# ============================================

@app.get("/api/analytics/summary")
async def get_analytics_summary(
    time_period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    # Check cache first
    cache_key = f"analytics_summary_{time_period or 'all'}"
    cached = get_cached_response(cache_key)
    if cached:
        return cached
    
    time_filter = get_time_filter(time_period)
    
    # Users
    user_query = db.query(User)
    if time_filter:
        user_query = user_query.filter(User.first_seen >= time_filter)
    
    total_users = user_query.count()
    new_users = user_query.filter(User.participation_level == "New to platform").count()
    enrolled_users = user_query.filter(User.participation_level == "Enrolled Participant").count()
    needs_counsellor = db.query(User).filter(User.needs_counsellor == True).count()
    
    enrolled_by_program = {}
    for program in ["LEP", "100BM", "MBW", "Masterclass"]:
        count = user_query.filter(User.enrolled_program.ilike(f"%{program}%")).count()
        enrolled_by_program[program] = count
    
    # Tickets
    ticket_query = db.query(Ticket)
    if time_filter:
        ticket_query = ticket_query.filter(Ticket.created_at >= time_filter)
    
    total_tickets = ticket_query.count()
    pending_tickets = ticket_query.filter(Ticket.status == "pending").count()
    resolved_tickets = ticket_query.filter(Ticket.status == "resolved").count()
    
    # Queries
    query_query = db.query(UserQuery)
    if time_filter:
        query_query = query_query.filter(UserQuery.created_at >= time_filter)
    
    total_queries = query_query.count()
    pending_queries = query_query.filter(UserQuery.status == "pending").count()
    call_requests = query_query.filter(UserQuery.contact_preference == "call").count()
    
    # Feedbacks
    feedback_query = db.query(Feedback)
    if time_filter:
        feedback_query = feedback_query.filter(Feedback.created_at >= time_filter)
    total_feedbacks = feedback_query.count()
    
    # Course interests
    course_stats = []
    for course in ["LEP", "100BM", "MBW", "Masterclass"]:
        ci_query = db.query(CourseInterest).filter(CourseInterest.course_name == course)
        if time_filter:
            ci_query = ci_query.filter(CourseInterest.first_clicked >= time_filter)
        
        total_clicks = db.query(func.sum(CourseInterest.click_count)).filter(
            CourseInterest.course_name == course
        )
        if time_filter:
            total_clicks = total_clicks.filter(CourseInterest.first_clicked >= time_filter)
        total_clicks = total_clicks.scalar() or 0
        
        course_stats.append({
            "course": course,
            "total_clicks": int(total_clicks),
            "unique_users": ci_query.count()
        })
    
    result = {
        "users": {
            "total": total_users,
            "new": new_users,
            "enrolled": enrolled_users,
            "needs_counsellor": needs_counsellor,
            "enrolled_by_program": enrolled_by_program
        },
        "tickets": {
            "total": total_tickets,
            "pending": pending_tickets,
            "resolved": resolved_tickets
        },
        "queries": {
            "total": total_queries,
            "pending": pending_queries,
            "call_requests": call_requests
        },
        "feedbacks": {
            "total": total_feedbacks
        },
        "course_interests": course_stats
    }
    
    # Cache the result
    set_cached_response(cache_key, result)
    return result


# ============================================
# WEBHOOK LOGS
# ============================================

@app.get("/api/webhook-logs")
async def get_webhook_logs(
    limit: int = 50,
    is_outgoing: Optional[bool] = None,
    db: Session = Depends(get_db)
):
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
                "message_id": log.message_id,
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
    log = db.query(WebhookLog).filter(WebhookLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    return {
        "id": log.id,
        "raw_data": json.loads(log.raw_data) if log.raw_data else None
    }


# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    zoho_configured = bool(ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN)
    
    print()
    print("=" * 60)
    print("🚀 Iron Lady WATI Analytics API v9.1.2 (FIXED)")
    print("=" * 60)
    print(f"📍 http://{API_HOST}:{API_PORT}")
    print(f"📚 Docs: http://{API_HOST}:{API_PORT}/docs")
    print(f"🔑 WATI: {'✅' if WATI_API_TOKEN else '❌'}")
    print(f"🔗 Zoho CRM: {'✅' if zoho_configured else '❌'}")
    print()
    print("✅ FIXES IN v9.1.2:")
    print("   1. Feedback capture - now works (moved before CRM routing)")
    print("   2. Counsellor query capture - now works with webhook log fallback")
    print("   3. Course interest users endpoint - /api/course-interests/{course_name}")
    print("   4. Restored 'speak_to_counsellor' and 'provide_feedback' message types")
    print("   5. Added duplicate feedback prevention (5 min window)")
    print("   6. Restored full analytics summary data")
    print("   7. Restored /api/queries endpoints")
    print()
    uvicorn.run(app, host=API_HOST, port=API_PORT)
