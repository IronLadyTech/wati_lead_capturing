"""
Iron Lady WATI Analytics - Database Reset Utility

Run this script when you need to reset the database:
- After updating models in main.py
- When you get database column errors
- To start fresh with clean data

Usage:
    python reset_db.py
"""

from sqlalchemy import create_engine, text
import os

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/wati_analytics")


def reset_database():
    """Drop all tables and let main.py recreate them"""
    
    print("=" * 50)
    print("🗄️  Iron Lady WATI Analytics - Database Reset")
    print("=" * 50)
    print()
    print(f"Database: {DATABASE_URL}")
    print()
    
    engine = create_engine(DATABASE_URL)
    
    print("🗑️  Dropping all tables...")
    
    with engine.connect() as conn:
        # Drop tables in correct order (foreign keys first)
        tables = [
            "feedbacks",
            "user_queries", 
            "course_interests",
            "webhook_logs",
            "users"
        ]
        
        for table in tables:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                print(f"   ✓ Dropped: {table}")
            except Exception as e:
                print(f"   ✗ Error dropping {table}: {e}")
        
        conn.commit()
    
    print()
    print("✅ All tables dropped successfully!")
    print()
    print("📋 Next steps:")
    print("   1. Run: python main.py")
    print("   2. Tables will be recreated automatically")
    print("   3. Test your WATI webhook")
    print()


def show_tables():
    """Show current table structure"""
    
    engine = create_engine(DATABASE_URL)
    
    print("📊 Current Tables:")
    print()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        
        tables = result.fetchall()
        
        if tables:
            for table in tables:
                print(f"   • {table[0]}")
                
                # Show columns
                cols = conn.execute(text(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = '{table[0]}'
                    ORDER BY ordinal_position
                """))
                
                for col in cols.fetchall():
                    print(f"      - {col[0]}: {col[1]}")
                print()
        else:
            print("   No tables found.")
    print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        show_tables()
    else:
        print()
        confirm = input("⚠️  This will DELETE all data. Type 'yes' to confirm: ")
        
        if confirm.lower() == "yes":
            reset_database()
        else:
            print()
            print("❌ Cancelled. No changes made.")
            print()
            print("💡 Tip: Run 'python reset_db.py show' to see current tables")
            print()