-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY NOT NULL,
    profile_name TEXT NOT NULL,
    age INTEGER CHECK (age > 0),
    banned BOOLEAN NOT NULL DEFAULT 0,
    suspended BOOLEAN NOT NULL DEFAULT 0,
    suspension_len INTEGER DEFAULT 0 CHECK (suspension_len >= 0),
    reported_law BOOLEAN NOT NULL DEFAULT 0, 
    risk_score REAL DEFAULT 50.0 CHECK (risk_score BETWEEN 0 AND 100),
    message_count INTEGER DEFAULT 0 CHECK (message_count >= 0)
);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    user_id TEXT NOT NULL,
    message_id TEXT PRIMARY KEY NOT NULL,
    conversation_id TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    grooming_suspected BOOLEAN NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
