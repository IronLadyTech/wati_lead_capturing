"""
Iron Lady WATI Analytics - Complete Backend
FastAPI server with WATI webhook receiver and analytics API

Author: Iron Lady Tech Team
Version: 3.0.2 - Fixed query detection for new numbers
"""

import json
import re
import os
from datetime import datetime, timedelta
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
# DATABASE MODELS
# ============================================

class User(Base):
    """User/Lead model - stores all contact information"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True)
    participation_level = Column(String(50), default="Unknown")  # "New to platform", "Enrolled Participant", "Unknown"
    enrolled_program = Column(String(100), nullable=True)  # Can be "LEP", "LEP,100BM", etc.
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
    course_name = Column(String(50), nullable=False)  # "LEP", "100BM", "MBW", "Masterclass"
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
    query_type = Column(String(30), default="general")  # "general", "counsellor_doubt", "i_have_query"
    contact_preference = Column(String(20), default="message")  # "message", "call"
    status = Column(String(30), default="pending")  # "pending", "in_progress", "resolved"
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
# DATABASE INITIALIZATION (Safe - preserves data)
# ============================================

def init_database():
    """
    Initialize database safely:
    1. Creates tables if they don't exist
    2. Adds missing columns without dropping data
    
    This replaces reset_db.py for most cases.
    """
    from sqlalchemy import inspect, text
    
    print("🔄 Initializing database...")
    
    # Step 1: Create all tables that don't exist
    Base.metadata.create_all(bind=engine)
    
    # Step 2: Define columns that might need to be added to existing tables
    # Format: (table_name, column_name, column_definition)
    column_updates = [
        # Users table
        ("users", "enrolled_program", "VARCHAR(100)"),
        ("users", "participation_level", "VARCHAR(50) DEFAULT 'Unknown'"),
        
        # User queries table
        ("user_queries", "query_type", "VARCHAR(30) DEFAULT 'general'"),
        ("user_queries", "contact_preference", "VARCHAR(20) DEFAULT 'message'"),
        ("user_queries", "resolved_by", "VARCHAR(100)"),
        ("user_queries", "resolution_notes", "TEXT"),
        ("user_queries", "updated_at", "TIMESTAMP DEFAULT NOW()"),
        
        # Webhook logs table
        ("webhook_logs", "is_outgoing", "BOOLEAN DEFAULT FALSE"),
        ("webhook_logs", "action_taken", "VARCHAR(100)"),
        
        # Feedbacks table
        ("feedbacks", "created_at", "TIMESTAMP DEFAULT NOW()"),
        
        # Course interests table
        ("course_interests", "click_count", "INTEGER DEFAULT 1"),
        ("course_interests", "first_clicked", "TIMESTAMP DEFAULT NOW()"),
        ("course_interests", "last_clicked", "TIMESTAMP DEFAULT NOW()"),
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
                            # PostgreSQL syntax with IF NOT EXISTS
                            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"))
                            print(f"   ✅ Added column: {table}.{column}")
                        except Exception as e:
                            # Silently ignore if column already exists
                            pass
            conn.commit()
        
        print("✅ Database ready!")
        
    except Exception as e:
        print(f"⚠️ Database init warning: {e}")
        print("   Tables will be created on first use.")


# Initialize database
init_database()

# ============================================
# FASTAPI APP
# ============================================

app = FastAPI(
    title="Iron Lady WATI Analytics API",
    description="Complete analytics backend for WATI WhatsApp chatbot",
    version="3.0.2",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware - allow all origins for development
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
# PYDANTIC MODELS (Request/Response)
# ============================================

class QueryUpdateRequest(BaseModel):
    """Request model for updating query status"""
    status: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None

# ============================================
# HELPER FUNCTIONS
# ============================================

# Messages to ignore (casual greetings)
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
    # Clean phone number
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
        # Update last interaction
        user.last_interaction = datetime.utcnow()
        
        # Update name/email if provided and not already set
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
    """Add program to user's enrolled_program (supports multiple)"""
    if not user.enrolled_program:
        user.enrolled_program = program
    elif program not in user.enrolled_program:
        user.enrolled_program = f"{user.enrolled_program},{program}"


def should_ignore_message(message: str) -> bool:
    """Check if message is casual greeting that should be ignored"""
    message_lower = message.lower().strip()
    return message_lower in IGNORE_MESSAGES or len(message.strip()) < 3


def extract_email(text: str) -> Optional[str]:
    """Extract email address from text"""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, text)
    return match.group() if match else None


def check_counsellor_flow_context(db: Session, wa_number: str) -> bool:
    """
    Check if user is in counsellor request flow by examining recent bot messages.
    This is a more robust check that looks at multiple recent messages.
    """
    # Look at last 10 outgoing bot messages for this user
    recent_logs = db.query(WebhookLog).filter(
        WebhookLog.phone_number == wa_number,
        WebhookLog.is_outgoing == True,
        WebhookLog.created_at >= datetime.utcnow() - timedelta(minutes=30)  # Within last 30 mins
    ).order_by(WebhookLog.created_at.desc()).limit(10).all()
    
    for rlog in recent_logs:
        if rlog.raw_data:
            try:
                rdata = json.loads(rlog.raw_data)
                rtext = (rdata.get("text", "") or "").lower()
                
                # Check for counsellor flow indicators
                if any(phrase in rtext for phrase in [
                    "please share any queries or doubts",
                    "queries or doubts you may have",
                    "counsellor will reach out",
                    "counsellor will call",
                    "connect you with a counsellor"
                ]):
                    return True
                    
                # Check action_taken field
                if rlog.action_taken in ["query_prompt_sent", "counsellor_confirmed"]:
                    return True
                    
            except:
                pass
    
    return False


def check_feedback_flow_context(db: Session, wa_number: str) -> bool:
    """
    Check if user is in feedback flow by examining recent bot messages.
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
    """Check if a message looks like a genuine query/question"""
    message_lower = message.lower()
    
    # Contains question mark
    if "?" in message:
        return True
    
    # Substantial length (more than casual message)
    if len(message) > 30:
        return True
    
    # Contains query-like keywords
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
# WEBHOOK ENDPOINT
# ============================================

@app.post("/webhook/wati")
async def wati_webhook(data: dict, db: Session = Depends(get_db)):
    """
    WATI Webhook Receiver - v3.0.2
    
    Processes incoming webhook events from WATI:
    - Incoming user messages
    - Outgoing bot messages (to detect button clicks)
    
    IMPROVED: More robust query detection for new numbers
    """
    
    # Extract data from webhook
    wa_number = data.get("waId") or data.get("waNumber") or ""
    sender_name = data.get("senderName", "").replace("~", "").strip() or None
    event_type = data.get("eventType", "")
    is_outgoing = data.get("owner", False) == True  # True = message FROM bot
    message_text = data.get("text", "") or ""
    message_lower = message_text.lower()
    
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
        # Skip if no phone number
        if not wa_number:
            log.action_taken = "ignored_no_phone"
            log.processed = True
            db.commit()
            return {"status": "ignored", "reason": "No phone number"}
        
        # Clean phone number
        wa_number = wa_number.replace("+", "").replace(" ", "")
        
        # Get or create user
        user = get_or_create_user(db, wa_number, name=sender_name)
        
        # ========================================
        # HANDLE OUTGOING BOT MESSAGES
        # This is how we detect button clicks!
        # ========================================
        
        if is_outgoing and message_text:
            
            # --- ENROLLMENT CONFIRMATION ---
            # "We are thrilled to inform you that your registration..."
            if "thrilled to inform" in message_lower and "registration" in message_lower:
                user.participation_level = "Enrolled Participant"
                
                # Detect which program
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
            
            # --- COURSE INFO: LEP ---
            # "Leadership Essentials Program enables you to master Business War Tactics"
            if "leadership essentials program enables you to master" in message_lower:
                update_course_interest(db, user.id, "LEP")
                log.action_taken = "course_interest_LEP"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_LEP"}
            
            # --- COURSE INFO: 100BM ---
            # "100 Board Members program enables you to focus fast tracking"
            if "100 board members program enables you to focus" in message_lower:
                update_course_interest(db, user.id, "100BM")
                log.action_taken = "course_interest_100BM"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_100BM"}
            
            # --- COURSE INFO: MBW ---
            # "Master of Business Warfare focuses on winning through war tactics"
            if "master of business warfare focuses on winning" in message_lower:
                update_course_interest(db, user.id, "MBW")
                log.action_taken = "course_interest_MBW"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_MBW"}
            
            # --- COURSE INFO: Masterclass ---
            # "Iron Lady Leadership masterclass helps you to learn"
            if "iron lady leadership masterclass helps you" in message_lower:
                update_course_interest(db, user.id, "Masterclass")
                log.action_taken = "course_interest_Masterclass"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "course_interest_Masterclass"}
            
            # --- PARTICIPATION: New to Platform ---
            # "Welcome to the Iron Lady Platform"
            if "welcome to the iron lady platform" in message_lower:
                user.participation_level = "New to platform"
                db.commit()
                log.action_taken = "participation_new"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "participation_new"}
            
            # --- PARTICIPATION: Enrolled Participant ---
            # "Ask a question here"
            if "ask a question here" in message_lower:
                user.participation_level = "Enrolled Participant"
                db.commit()
                log.action_taken = "participation_enrolled"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "participation_enrolled"}
            
            # --- COUNSELLOR CONFIRMATION ---
            # "Our counsellor will reach out to you within next 48 hours"
            if "counsellor will reach out to you" in message_lower:
                log.action_taken = "counsellor_confirmed"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "counsellor_confirmed"}
            
            # --- FEEDBACK THANK YOU ---
            if "thank you for your valueable feedback" in message_lower:
                log.action_taken = "feedback_confirmed"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "feedback_confirmed"}
            
            # --- QUERY PROMPT ---
            # "Please share any queries or doubts you may have"
            if "please share any queries or doubts" in message_lower:
                log.action_taken = "query_prompt_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "query_prompt_sent"}
            
            # --- FEEDBACK PROMPT ---
            if "please provide your feedback here" in message_lower:
                log.action_taken = "feedback_prompt_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "feedback_prompt_sent"}
            
            # --- I HAVE QUERY FORM PROMPT ---
            if "please fill below form" in message_lower:
                log.action_taken = "query_form_sent"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "query_form_sent"}
            
            # Other bot messages
            log.action_taken = "bot_message_logged"
            log.processed = True
            db.commit()
            return {"status": "processed", "action": "bot_message_logged"}
        
        # ========================================
        # HANDLE INCOMING USER MESSAGES
        # IMPROVED: More robust detection for new numbers
        # ========================================
        
        if not is_outgoing and message_text:
            
            # --- EMAIL CAPTURE ---
            email = extract_email(message_text)
            if email:
                user.email = email
                db.commit()
                log.action_taken = "email_captured"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "email_captured", "email": email}
            
            # --- IGNORE CASUAL MESSAGES ---
            if should_ignore_message(message_text):
                log.action_taken = "casual_ignored"
                log.processed = True
                db.commit()
                return {"status": "processed", "action": "casual_ignored"}
            
            # --- CHECK CONTEXT FROM LAST BOT MESSAGE ---
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
            
            # ========================================
            # COUNSELLOR QUERY DETECTION - IMPROVED
            # Uses multiple detection methods
            # ========================================
            
            # Method 1: Direct context check (last bot message)
            is_counsellor_query_context = "please share any queries or doubts" in recent_bot_text
            
            # Method 2: Extended context check (look at recent conversation flow)
            is_in_counsellor_flow = check_counsellor_flow_context(db, wa_number)
            
            # Method 3: Check if there's NO existing query from this user in last 5 minutes
            five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
            recent_query_exists = db.query(UserQuery).filter(
                UserQuery.user_id == user.id,
                UserQuery.created_at >= five_mins_ago
            ).first() is not None
            
            # --- COUNSELLOR QUERY ---
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
            
            # --- FEEDBACK ---
            # Check both direct context and extended flow
            is_feedback_context = "please provide your feedback here" in recent_bot_text
            is_in_feedback_flow = check_feedback_flow_context(db, wa_number)
            
            if is_feedback_context or is_in_feedback_flow:
                # Check if feedback already exists in last 5 mins
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
            
            # --- GENERAL QUERY (Fallback) ---
            # If message looks like a genuine question and no recent query exists
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
            
            # --- OTHER MESSAGES ---
            log.action_taken = "message_logged"
            log.processed = True
            db.commit()
            return {"status": "processed", "action": "message_logged"}
        
        # Default
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
    """API root - shows basic info"""
    return {
        "name": "Iron Lady WATI Analytics API",
        "version": "3.0.2",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        user_count = db.query(User).count()
        return {
            "status": "healthy",
            "database": "connected",
            "total_users": user_count,
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
        # Get course interests
        courses = db.query(CourseInterest.course_name).filter(
            CourseInterest.user_id == user.id
        ).distinct().all()
        course_list = [c[0] for c in courses]
        
        # Check for pending call requests
        has_call_request = db.query(UserQuery).filter(
            UserQuery.user_id == user.id,
            UserQuery.contact_preference == "call",
            UserQuery.status == "pending"
        ).first() is not None
        
        # Check for pending message queries
        has_message_query = db.query(UserQuery).filter(
            UserQuery.user_id == user.id,
            UserQuery.contact_preference == "message",
            UserQuery.status == "pending"
        ).first() is not None
        
        # Get latest feedback
        latest_feedback = db.query(Feedback).filter(
            Feedback.user_id == user.id
        ).order_by(Feedback.created_at.desc()).first()
        
        # Query count
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
            "first_seen": user.first_seen.isoformat() if user.first_seen else None,
            "last_interaction": user.last_interaction.isoformat() if user.last_interaction else None
        })
    
    return {"users": result, "total": len(result)}


@app.get("/api/users/{user_id}")
async def get_user_details(user_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a specific user"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get course interests
    course_interests = db.query(CourseInterest).filter(
        CourseInterest.user_id == user.id
    ).all()
    
    # Get queries
    queries = db.query(UserQuery).filter(
        UserQuery.user_id == user.id
    ).order_by(UserQuery.created_at.desc()).all()
    
    # Get feedbacks
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
            "first_seen": user.first_seen.isoformat() if user.first_seen else None,
            "last_interaction": user.last_interaction.isoformat() if user.last_interaction else None
        },
        "course_interests": [
            {
                "course_name": ci.course_name,
                "click_count": ci.click_count,
                "first_clicked": ci.first_clicked.isoformat() if ci.first_clicked else None,
                "last_clicked": ci.last_clicked.isoformat() if ci.last_clicked else None
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
                "created_at": q.created_at.isoformat() if q.created_at else None
            }
            for q in queries
        ],
        "feedbacks": [
            {
                "id": f.id,
                "feedback_text": f.feedback_text,
                "created_at": f.created_at.isoformat() if f.created_at else None
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
            "created_at": q.created_at.isoformat() if q.created_at else None
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
            "first_clicked": ci.first_clicked.isoformat() if ci.first_clicked else None,
            "last_clicked": ci.last_clicked.isoformat() if ci.last_clicked else None
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
            "created_at": f.created_at.isoformat() if f.created_at else None
        })
    
    return {"feedbacks": result, "total": len(result)}


# ============================================
# ANALYTICS SUMMARY ENDPOINT
# ============================================

@app.get("/api/analytics/summary")
async def get_analytics_summary(db: Session = Depends(get_db)):
    """Get overall analytics summary for dashboard"""
    
    # User counts
    total_users = db.query(User).count()
    new_users = db.query(User).filter(User.participation_level == "New to platform").count()
    enrolled_users = db.query(User).filter(User.participation_level == "Enrolled Participant").count()
    
    # Enrolled by program
    enrolled_by_program = {}
    for program in ["LEP", "100BM", "MBW", "Masterclass"]:
        count = db.query(User).filter(
            User.enrolled_program.ilike(f"%{program}%")
        ).count()
        enrolled_by_program[program] = count
    
    # Query counts
    total_queries = db.query(UserQuery).count()
    pending_queries = db.query(UserQuery).filter(UserQuery.status == "pending").count()
    call_requests = db.query(UserQuery).filter(UserQuery.contact_preference == "call").count()
    counsellor_doubts = db.query(UserQuery).filter(UserQuery.query_type == "counsellor_doubt").count()
    
    # Feedback count
    total_feedbacks = db.query(Feedback).count()
    
    # Course interest stats
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
        "course_interests": course_stats
    }


# ============================================
# WEBHOOK LOGS ENDPOINT (for debugging)
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
                "created_at": log.created_at.isoformat() if log.created_at else None
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
    print("🚀 Iron Lady WATI Analytics API v3.0.2")
    print("=" * 50)
    print()
    print(f"📍 Server: http://{API_HOST}:{API_PORT}")
    print(f"📚 API Docs: http://{API_HOST}:{API_PORT}/docs")
    print(f"🔗 Webhook URL: http://your-server:{API_PORT}/webhook/wati")
    print()
    print("=" * 50)
    print()
    
    uvicorn.run(app, host=API_HOST, port=API_PORT)