import os
import sqlite3
from sqlite3 import Error

CONFIDENCE_THRESHOLD = 0.8  # Threshold for high confidence score
BAN_THRESHOLD = 75
SUSPEND_THRESHOLD = 65
REPORT_THRESHOLD = 80
MESSAGE_THRESHOLD = 5     # Threshold for message count



def create_connection():

    """Create a database connection to SQLite."""
    conn = None
    try:
        conn = sqlite3.connect('backend/user_stats.db')
        # print("Connected to SQLite database.")
    except Error as e:
        print(f"Error connecting to database: {e}")
    return conn

def initialize_database():
    """Initialize tables and trigger (idempotent)."""
    if os.path.exists('backend/user_stats.db'):
        os.remove('backend/user_stats.db')

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
def log_conversation(user_id, message_id, conversation_id, confidence_score, grooming_suspected, ml_risk_score):
    """Log a conversation with its details and update reputation score if necessary."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (user_id, message_id, conversation_id, confidence_score, grooming_suspected) VALUES (?, ?, ?, ?, ?)",
                (user_id, message_id, conversation_id, confidence_score, grooming_suspected)
            )
            update_risk_score(cursor, user_id, ml_risk_score)
            conn.commit()

            print(f"Logged conversation with message_id '{message_id}' and score {confidence_score} for user '{user_id}'.")
        except Error as e:
            print(f"Error logging conversation: {e}")
        finally:
            conn.close()

def update_risk_score(cursor, user_id, ml_risk_score):
    """Update the risk score for a user."""
    cursor.execute(
        "SELECT message_count FROM users WHERE user_id = ?",
        (user_id,)
    )
    user_data = cursor.fetchone()
    message_count = user_data[0]
    message_count += 1

    # If message count is high, use ml_risk_score directly
    if message_count < MESSAGE_THRESHOLD:
        overall_risk_score = ml_risk_score * (message_count / MESSAGE_THRESHOLD)
    # If message count is low, adjust the risk score
    else:
        overall_risk_score = ml_risk_score 
    # For moderate message counts, interpolate between ml_risk_score and a baseline
    # else:
    #     overall_risk_score = ml_risk_score * (message_count / HIGH_MESSAGE_THRESHOLD)

    # Update risk score and message count
    cursor.execute(
        "UPDATE users SET risk_score = ?, message_count = ? WHERE user_id = ?",
        (overall_risk_score, message_count, user_id)
    )
    print(f"Updated risk score for user '{user_id}' to {overall_risk_score}.")

def get_user_stats(user_id):
    """Retrieve a user's stats and confidence scores in insertion order."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT profile_name, age, banned, suspended, suspension_len, reported_law, risk_score, message_count FROM users WHERE user_id = ?",
                (user_id,)
            )
            user = cursor.fetchone()
            if not user:
                print(f"No user found with user_id '{user_id}'.")
                return None
            cursor.execute(
                "SELECT message_id, conversation_id, confidence_score, grooming_suspected, timestamp FROM conversations WHERE user_id = ? ORDER BY timestamp",
                (user_id,)
            )
            conversations = cursor.fetchall()
            return {
                "profile_name": user[0],
                "user_id": user_id,
                "age": user[1],
                "banned": user[2],
                "suspended": user[3],
                "suspension_len": user[4],
                "reported_law": user[5],
                "risk_score": user[6],
                "conversations": [
                    {"message_id": message_id, "conversation_id": conversation_id, "confidence_score": confidence_score, "grooming_suspected": grooming_suspected, "timestamp": timestamp}
                    for message_id, conversation_id, confidence_score, grooming_suspected, timestamp in conversations
                ]
            }
        except Error as e:
            print(f"Error fetching user stats: {e}")
        finally:
            conn.close()

def update_ban(user_id, profile_name, banned):
    """Update ban status on the backend."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                    "UPDATE users SET banned = ? WHERE user_id = ?",
                    (banned, user_id)
                )
            conn.commit()
            print(f"Banned user '{user_id}' with username {profile_name}.")
        except Error as e:
            print(f"Error banning user {user_id}: {e}")
        finally:
            conn.close()

def update_suspension(user_id, profile_name, suspended, len):
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                    "UPDATE users SET suspended = ?, suspension_len = ? WHERE user_id = ?",
                    (suspended, len, user_id)
                )
            conn.commit()
            print(f"Suspended user '{user_id}' with username {profile_name} for {len} days.")
        except Error as e:
            print(f"Error suspending user {user_id}: {e}")
        finally:
            conn.close()

def update_report_to_law(user_id, profile_name, banned, reported):
    """Update ban status on the backend."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                    "UPDATE users SET banned = ?, reported_law = ? WHERE user_id = ?",
                    (banned, reported, user_id)
                )
            conn.commit()
            print(f"Reported to law enforcement user '{user_id}' with username {profile_name}.")
        except Error as e:
            print(f"Error reporting to law enforcement user {user_id}: {e}")
        finally:
            conn.close()
