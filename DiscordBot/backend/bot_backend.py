import sqlite3
from sqlite3 import Error

CONFIDENCE_THRESHOLD = 0.8  # Example threshold for high confidence score

def create_connection():
    """Create a database connection to SQLite."""
    conn = None
    try:
        conn = sqlite3.connect('backend/user_stats.db')
        print("Connected to SQLite database.")
    except Error as e:
        print(f"Error connecting to database: {e}")
    return conn

def initialize_database():
    """Initialize tables and trigger (idempotent)."""
    conn = create_connection()
    if conn:
        try:
            with open('backend/schema.sql', 'r') as f:
                schema = f.read()
            conn.executescript(schema)
            print("Database initialized.")
        except Error as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()

def add_user(user_id, profile_name, age=None):
    """Add a new user to the database."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (user_id, profile_name, age) VALUES (?, ?, ?)",
                (user_id, profile_name, age)
            )
            conn.commit()
            print(f"User '{profile_name}' added with user_id '{user_id}'.")
        except sqlite3.IntegrityError as e:
            print(f"Error: {e}")
        finally:
            conn.close()

def check_user_exists(user_id):
    """Check if a user exists in the database."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM users WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            if result:
                return True
            else:
                return False
        except Error as e:
            print(f"Error checking if user exists: {e}")
            return False
        finally:
            conn.close()

# Conversation_id instead of message_id. also need ids of both users.
def log_conversation(user_id, message_id, conversation_id, confidence_score, grooming_suspected):
    """Log a conversation with its details and update reputation score if necessary."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (user_id, message_id, conversation_id, confidence_score, grooming_suspected) VALUES (?, ?, ?, ?, ?)",
                (user_id, message_id, conversation_id,confidence_score, grooming_suspected)
            )
            # Update reputation score only if criteria are met
            if confidence_score >= CONFIDENCE_THRESHOLD and grooming_suspected:
                cursor.execute(
                    "SELECT reputation_score FROM users WHERE user_id = ?",
                    (user_id,)
                )
                reputation_score = cursor.fetchone()[0]
                # Decrease reputation score
                # Think about number of conversations as well
                new_reputation_score = max(0, reputation_score - ((confidence_score - CONFIDENCE_THRESHOLD) * 100))
                cursor.execute(
                    "UPDATE users SET reputation_score = ? WHERE user_id = ?",
                    (new_reputation_score, user_id)
                )
            conn.commit()
            print(f"Logged conversation with message_id '{message_id}' and score {confidence_score} for user '{user_id}'.")
        except Error as e:
            print(f"Error logging conversation: {e}")
        finally:
            conn.close()

def get_user_stats(user_id):
    """Retrieve a user's stats and confidence scores in insertion order."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT profile_name, age, reputation_score FROM users WHERE user_id = ?",
                (user_id,)
            )
            user = cursor.fetchone()
            if not user:
                print(f"No user found with user_id '{user_id}'.")
                return None
            cursor.execute(
                "SELECT message_id, confidence_score, grooming_suspected, timestamp FROM conversations WHERE user_id = ? ORDER BY timestamp",
                (user_id,)
            )
            conversations = cursor.fetchall()
            return {
                "profile_name": user[0],
                "user_id": user_id,
                "age": user[1],
                "reputation_score": user[2],
                "conversations": [
                    {"message_id": message_id, "confidence_score": confidence_score, "grooming_suspected": grooming_suspected, "timestamp": timestamp}
                    for message_id, confidence_score, grooming_suspected, timestamp in conversations
                ]
            }
        except Error as e:
            print(f"Error fetching user stats: {e}")
        finally:
            conn.close()

