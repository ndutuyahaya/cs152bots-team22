import sqlite3
from sqlite3 import Error

CONFIDENCE_THRESHOLD = 0.8  # Example threshold for high confidence score

def create_connection():
    """Create a database connection to SQLite."""
    conn = None
    try:
        conn = sqlite3.connect('user_stats.db')
        print("Connected to SQLite database.")
    except Error as e:
        print(f"Error connecting to database: {e}")
    return conn

def initialize_database():
    """Initialize tables and trigger (idempotent)."""
    conn = create_connection()
    if conn:
        try:
            with open('schema.sql', 'r') as f:
                schema = f.read()
            conn.executescript(schema)
            print("Database initialized.")
        except Error as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()

def add_user(user_id, profile_name, age):
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
            print(f"Error: {e} (likely duplicate user_id)")
        finally:
            conn.close()

def log_conversation(user_id, message_id, confidence_score, grooming_suspected):
    """Log a conversation with its details and update reputation score if necessary."""
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (user_id, message_id, confidence_score, grooming_suspected) VALUES (?, ?, ?, ?)",
                (user_id, message_id, confidence_score, grooming_suspected)
            )
            # Update reputation score only if criteria are met
            if confidence_score >= CONFIDENCE_THRESHOLD and grooming_suspected:
                cursor.execute(
                    "SELECT reputation_score FROM users WHERE user_id = ?",
                    (user_id,)
                )
                reputation_score = cursor.fetchone()[0]
                # Decrease reputation score
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

# Example Usage
if __name__ == "__main__":
    initialize_database()

    # Add a user
    user_id = "BobistheMan"
    add_user(user_id, "Bobbit", 47)
    
    # Log conversations (simulate bot interactions)
    log_conversation(user_id, "m001xABC", 0.85, True)  # Reputation should decrease
    log_conversation(user_id, "m002xABC", 0.92, True)  # Reputation should decrease further
    log_conversation(user_id, "m003xabc", 0.45, False) # No reputation change
    
    # Fetch stats
    stats = get_user_stats(user_id)
    if stats:
        print(f"\nUser Stats for {stats['profile_name']}:")
        print(f"  Age: {stats['age']}")
        print(f"  Reputation Score: {stats['reputation_score']:.2f}")
        print("  Conversations:")
        for convo in stats['conversations']:
            print(f"    - Message: {convo['message_id']}, Confidence: {convo['confidence_score']}, Grooming Suspected: {convo['grooming_suspected']}, Timestamp: {convo['timestamp']}")