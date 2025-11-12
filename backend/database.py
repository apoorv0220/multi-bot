import os
import pymysql
import uuid
import logging
import json # Import the json module
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger("migraine-chatbot")

class ChatDatabase:
    def __init__(self):
        self.host = os.getenv("WORDPRESS_DB_HOST")
        self.port = int(os.getenv("WORDPRESS_DB_PORT", 3306))
        self.user = os.getenv("WORDPRESS_DB_USER")
        self.password = os.getenv("WORDPRESS_DB_PASSWORD")
        self.database = os.getenv("WORDPRESS_DB_NAME")

    def get_connection(self):
        try:
            return pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
        except Exception as e:
            print(f"Error connecting to WordPress database: {e}")
            logger.exception(f"Error connecting to WordPress database in database.py: {e}")
            return None

    def get_or_create_session(self, session_uuid: str = None) -> dict:
        connection = self.get_connection()
        logger.info(f"Connection: {connection}")
        if not connection:
            return None

        try:
            with connection.cursor() as cursor:
                if session_uuid:
                    # Try to find existing session
                    query = "SELECT id, session_id FROM wp_chatbot_sessions WHERE session_id = %s"
                    cursor.execute(query, (session_uuid,))
                    session = cursor.fetchone()
                    if session:
                        return session

                # Create new session if not found or no session_uuid provided
                new_session_uuid = str(uuid.uuid4())
                logger.info(f"New session UUID: {new_session_uuid}")
                insert_query = "INSERT INTO wp_chatbot_sessions (session_id) VALUES (%s)"
                cursor.execute(insert_query, (new_session_uuid,))
                connection.commit()

                cursor.execute("SELECT id, session_id FROM wp_chatbot_sessions WHERE session_id = %s", (new_session_uuid,))
                logger.info("New session data retrieved from database.py")
                return cursor.fetchone()
        except Exception as e:
            print(f"Error getting or creating session: {e}")
            logger.exception(f"Error getting or creating session in database.py: {e}")
            connection.rollback()
            return None
        finally:
            connection.close()

    def save_chat_event(self, event_data: dict):
        connection = self.get_connection()
        if not connection:
            return False

        try:
            with connection.cursor() as cursor:
                # Prepare data for insertion
                columns = []
                values_placeholders = []
                values = []

                # Always include chatbot_session_id and event_type
                columns.append("chatbot_session_id")
                values_placeholders.append("%s")
                values.append(event_data["chatbot_session_id"])

                columns.append("event_type")
                values_placeholders.append("%s")
                values.append(event_data["event_type"])

                # Handle JSON serialization for bot_response_source
                if "bot_response_source" in event_data and isinstance(event_data["bot_response_source"], dict):
                    columns.append("bot_response_source")
                    values_placeholders.append("%s")
                    values.append(json.dumps(event_data["bot_response_source"]))
                elif "bot_response_source" in event_data and event_data["bot_response_source"] is not None:
                    # Fallback for non-JSON strings if needed, though we expect JSON dicts now
                    columns.append("bot_response_source")
                    values_placeholders.append("%s")
                    values.append(event_data["bot_response_source"])

                # Conditionally include other fields (restored)
                if "user_message_text" in event_data:
                    columns.append("user_message_text")
                    values_placeholders.append("%s")
                    values.append(event_data["user_message_text"])
                if "bot_response_text" in event_data:
                    columns.append("bot_response_text")
                    values_placeholders.append("%s")
                    values.append(event_data["bot_response_text"])
                if "bot_response_confidence" in event_data:
                    columns.append("bot_response_confidence")
                    values_placeholders.append("%s")
                    values.append(event_data["bot_response_confidence"])
                if "trigger_detection_method" in event_data:
                    columns.append("trigger_detection_method")
                    values_placeholders.append("%s")
                    values.append(event_data["trigger_detection_method"])
                if "trigger_confidence" in event_data:
                    columns.append("trigger_confidence")
                    values_placeholders.append("%s")
                    values.append(event_data["trigger_confidence"])
                if "trigger_matched_phrase" in event_data:
                    columns.append("trigger_matched_phrase")
                    values_placeholders.append("%s")
                    values.append(event_data["trigger_matched_phrase"])

                query = f"INSERT INTO wp_chatbot_events ({', '.join(columns)}) VALUES ({', '.join(values_placeholders)})"
                cursor.execute(query, tuple(values))
                connection.commit()
                return True
        except Exception as e:
            print(f"Error saving chat event: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()

    def get_chat_history(self, session_id: str) -> list:
        connection = self.get_connection()
        if not connection:
            return []

        try:
            with connection.cursor() as cursor:
                # First get the internal chatbot_session_id from wp_chatbot_sessions
                session_query = "SELECT id FROM wp_chatbot_sessions WHERE session_id = %s"
                cursor.execute(session_query, (session_id,))
                session_result = cursor.fetchone()

                if not session_result:
                    return [] # Session not found

                chatbot_internal_session_id = session_result['id']

                # Then fetch all events for this internal session ID
                history_query = """
                SELECT 
                    event_type, 
                    event_timestamp, 
                    user_message_text, 
                    bot_response_text, 
                    bot_response_source, 
                    bot_response_confidence, 
                    trigger_detection_method, 
                    trigger_confidence, 
                    trigger_matched_phrase
                FROM 
                    wp_chatbot_events 
                WHERE 
                    chatbot_session_id = %s 
                ORDER BY 
                    event_timestamp ASC
                """
                cursor.execute(history_query, (chatbot_internal_session_id,))
                history = cursor.fetchall()

                # Deserialize bot_response_source for each event
                for event in history:
                    if event.get('bot_response_source'):
                        try:
                            event['bot_response_source'] = json.loads(event['bot_response_source'])
                        except json.JSONDecodeError:
                            # Handle cases where it's not valid JSON (e.g., old string data)
                            pass 
                return history
        except Exception as e:
            print(f"Error retrieving chat history: {e}")
            return []
        finally:
            connection.close()
