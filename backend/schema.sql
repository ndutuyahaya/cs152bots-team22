-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY NOT NULL,
    profile_name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK (age > 0),
    reputation_score REAL DEFAULT 100.0 CHECK (reputation_score BETWEEN 0 AND 100)
);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    user_id TEXT NOT NULL,
    message_id TEXT PRIMARY KEY NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    grooming_suspected BOOLEAN NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
