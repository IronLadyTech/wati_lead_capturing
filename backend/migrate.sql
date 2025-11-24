-- ============================================
-- DATABASE MIGRATION SCRIPT
-- Run this if you're upgrading from v3.0.x to v3.1.0
-- ============================================

-- Add conversation_state column to users table (for tracking context)
ALTER TABLE users ADD COLUMN IF NOT EXISTS conversation_state VARCHAR(50) DEFAULT 'none';
ALTER TABLE users ADD COLUMN IF NOT EXISTS state_updated_at TIMESTAMP DEFAULT NOW();

-- Verify the columns were added
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
AND column_name IN ('conversation_state', 'state_updated_at');

-- Check current user states (should all be 'none' or null initially)
SELECT id, phone_number, name, conversation_state, state_updated_at 
FROM users 
LIMIT 10;

-- ============================================
-- OPTIONAL: Reset all user states (use if needed)
-- ============================================
-- UPDATE users SET conversation_state = 'none', state_updated_at = NOW();