# sections of system prompt
import os
import json
import datetime
import time
from datetime import timezone
import pandas as pd
from sqlalchemy import create_engine, text
from snowflake.sqlalchemy import URL
from dotenv import load_dotenv
from models import SessionLocal, QueryResult
from models import ChatHistory
from snowflake_utils2 import query_snowflake, get_schema_details
from groq_utils2 import get_groq_response
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from PIL import Image
import base64
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from syn import correct_user_question_enhanced
from continuation_detection import check_and_handle_continuation
from sql_query_fixer import fix_generated_sql
# ------------------------
# Constants for Autosave
# ------------------------
AUTOSAVE_ENABLED = True
AUTOSAVE_INTERVAL = 60  # Backup save every 60 seconds (in case immediate save fails)
IMMEDIATE_SAVE_ENABLED = True  # Enable saving after each Q&A exchange

# ------------------------
# 1. Load environment vars
# ------------------------
load_dotenv()

# ------------------------
# 2. Streamlit configuration
# ------------------------
st.set_page_config(
    page_title="❄️ AI Data Assistant ❄️ ",
    page_icon="❄️",
    layout="wide"
)


# Apply custom CSS
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


local_css("style.css")


# ------------------------
# 3. Helper: get Snowflake private key
# ------------------------
def get_private_key_str():
    private_key_content = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    if private_key_content:
        private_key_obj = serialization.load_pem_private_key(
            private_key_content.encode(),
            password=None,
            backend=default_backend()
        )
        der_private_key = private_key_obj.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        return base64.b64encode(der_private_key).decode('utf-8')
    else:
        raise ValueError("Private key not found in environment variables")


# ------------------------
# 4. Connect to Snowflake
# ------------------------
def get_snowflake_connection():
    return create_engine(URL(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        private_key=get_private_key_str(),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        role=os.getenv("SNOWFLAKE_ROLE")
    ))


# ------------------------
# 5. User Authentication
# ------------------------
def authenticate_user(email, password):
    if not email.endswith("@ahs.com"):
        return False
    engine = get_snowflake_connection()
    with engine.connect() as conn:
        query = text("SELECT COUNT(*) FROM UserPasswordName WHERE username = :email AND password = :password")
        result = conn.execute(query, {"email": email, "password": password}).fetchone()
        return result[0] > 0


def needs_password_change(email):
    engine = get_snowflake_connection()
    with engine.connect() as conn:
        query = text("SELECT initial FROM UserPasswordName WHERE username = :email")
        result = conn.execute(query, {"email": email}).fetchone()
        return result[0] if result else False


def update_password(email, new_password):
    engine = get_snowflake_connection()
    with engine.connect() as conn:
        query = text("UPDATE UserPasswordName SET password = :new_password, initial = FALSE WHERE username = :email")
        conn.execute(query, {"new_password": new_password, "email": email})
        conn.commit()


# ------------------------
# Updated Login and Password Change Pages with Forest Background
# ------------------------

def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()


def set_png_as_page_bg(png_file):
    bin_str = get_base64_of_bin_file(png_file)
    page_bg_img = f"""
    <style>
    .stApp {{
        /* Dark gradient overlay for better legibility */
        background: linear-gradient(
            rgba(0, 0, 0, 0.4),
            rgba(0, 0, 0, 0.4)
        ), url("data:image/png;base64,{bin_str}") no-repeat center center fixed;
        background-size: cover;
    }}
    </style>
    """
    return page_bg_img


def login_page():
    # Set the forest background with gradient overlay
    st.markdown(set_png_as_page_bg('bg.jpg'), unsafe_allow_html=True)

    # Load Montserrat font from Google Fonts
    st.markdown(
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet">',
        unsafe_allow_html=True
    )

    # Apply custom CSS
    st.markdown("""
    <style>
    /* Hide Streamlit's default UI elements */
    #MainMenu, footer, header {
        visibility: hidden;
    }

    /* Fade-in animation for the form container */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Style the login box (the middle column) */
    .stColumn:nth-child(2) {
        max-width: 450px;
        margin: 0 auto;
        padding: 30px;
        margin-top: 100px;
        background-color: rgba(255, 255, 255, 0.75);
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(10px);
        animation: fadeIn 0.8s ease-in-out;
    }

    /* Heading style */
    .login-heading {
        font-family: 'Montserrat', sans-serif;
        font-size: 36px;
        font-weight: 700;
        text-align: center;
        margin-bottom: 30px;
        color: #000000;
        text-transform: uppercase;
    }

    /* Input labels */
    .custom-label {
        font-family: 'Montserrat','Segoe UI',Arial, sans-serif;
        font-size: 18px;
        color: #000;
        font-weight: 700;
        margin-bottom: 4px;
    }

    /* Input fields */
    .stTextInput > div > div > input {
        background-color: #F5F5F5;
        border: 1px solid #666666;
        padding: 14px 18px;
        border-radius: 5px;
        font-family: 'Montserrat', sans-serif;
        font-size: 18px;
        color: #000000;
        font-weight: 500;
        transition: border-color 0.3s ease;
    }

    /* Focus state for input fields */
    .stTextInput > div > div > input:focus {
        outline: none !important;
        border: 2px solid #1A237E;
    }

    /* Login button */
    .stButton > button {
        font-family: 'Montserrat', sans-serif;
        background-color: #1A237E;
        color: #FFFFFF;
        font-weight: 600;
        font-size: 18px;
        border: none;
        padding: 14px 0;
        border-radius: 5px;
        width: 100%;
        margin-top: 10px;
        transition: background-color 0.3s ease, transform 0.2s ease;
        cursor: pointer;
    }

    /* Hover effect on login button */
    .stButton > button:hover {
        background-color: #283593;
        transform: translateY(-2px);
    }

    /* Spacing between inputs */
    .stTextInput {
        margin-bottom: 18px;
    }

    /* Responsive design */
    @media (max-width: 768px) {
        .stColumn:nth-child(2) {
            margin-top: 50px;
            padding: 20px;
        }
    }

    /* Style for messages (e.g., Checking credentials...) */
    .message-text {
        color: #000000;
        font-weight: bold;
        font-family: 'Montserrat', sans-serif;
        text-align: center;
        margin-top: 10px;
        font-size: 18px;
    }
    .error-text {
        color: #FF0000;
        font-weight: bold;
        font-family: 'Montserrat', sans-serif;
        text-align: center;
        margin-top: 10px;
        font-size: 18px;
    }
    </style>
    """, unsafe_allow_html=True)

    # Center the login box with columns
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        # Heading
        st.markdown("<h1 class='login-heading'>Login</h1>", unsafe_allow_html=True)

        # Form elements with placeholder text and icons for intuitive UI
        st.markdown("<div class='custom-label'>Email</div>", unsafe_allow_html=True)
        email = st.text_input("Email", placeholder="✉️ Enter your email", key="login_email", label_visibility="collapsed")
        st.markdown("<div class='custom-label'>Password</div>", unsafe_allow_html=True)
        password = st.text_input("Password", type="password", placeholder="🔒 Enter your password", key="login_password", label_visibility="collapsed")
        login_button = st.button("Login", key="login_button", use_container_width=True)

        # Placeholder for loading messages
        placeholder = st.empty()

        # Login logic with loading messages
        if login_button:
            placeholder.markdown("<div class='message-text'>Checking credentials...</div>", unsafe_allow_html=True)
            time.sleep(1)  # Simulate processing delay
            if authenticate_user(email, password):
                placeholder.markdown("<div class='message-text'>Loading your chat interface...</div>",
                                     unsafe_allow_html=True)
                time.sleep(1)  # Ensure the message is visible
                st.session_state["authenticated"] = True
                st.session_state["user"] = email
                st.rerun()
            else:
                placeholder.markdown("<div class='error-text'>Invalid credentials! Please try again.</div>",
                                     unsafe_allow_html=True)


def password_change_page():
    # Set the forest background with gradient overlay
    st.markdown(set_png_as_page_bg('bg.jpg'), unsafe_allow_html=True)

    # Load Montserrat font
    st.markdown(
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet">',
        unsafe_allow_html=True
    )

    # Apply custom CSS
    st.markdown("""
    <style>
    /* Hide Streamlit's default UI elements */
    #MainMenu, footer, header {
        visibility: hidden;
    }

    /* Fade-in animation for the password change container */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .stColumn:nth-child(2) {
        max-width: 450px;
        margin: 0 auto;
        padding: 30px;
        margin-top: 100px;
        background-color: rgba(255, 255, 255, 0.75);
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(10px);
        animation: fadeIn 0.8s ease-in-out;
    }

    /* Heading style */
    .password-heading {
        font-family: 'Montserrat', sans-serif;
        font-size: 36px;
        font-weight: 700;
        text-align: center;
        margin-bottom: 30px;
        color: #000000;
        text-transform: uppercase;
    }

    /* Input labels */
    .custom-label {
        font-family: 'Montserrat','Segoe UI',Arial, sans-serif;
        font-size: 18px;
        color: #000;
        font-weight: 700;
        margin-bottom: 4px;
    }

    /* Input fields */
    .stTextInput > div > div > input {
        background-color: #F5F5F5;
        border: 1px solid #666666;
        padding: 14px 18px;
        border-radius: 5px;
        font-family: 'Montserrat', sans-serif;
        font-size: 18px;
        color: #000000;
        font-weight: 500;
        transition: border-color 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
        outline: none !important;
        border: 2px solid #1A237E;
    }

    /* Change password button */
    .stButton > button {
        font-family: 'Montserrat', sans-serif;
        background-color: #1A237E;
        color: #FFFFFF;
        font-weight: 600;
        font-size: 18px;
        border: none;
        padding: 14px 0;
        border-radius: 5px;
        width: 100%;
        margin-top: 10px;
        transition: background-color 0.3s ease, transform 0.2s ease;
        cursor: pointer;
    }

    .stButton > button:hover {
        background-color: #283593;
        transform: translateY(-2px);
    }

    /* Spacing between inputs */
    .stTextInput {
        margin-bottom: 18px;
    }

    /* Responsive design */
    @media (max-width: 768px) {
        .stColumn:nth-child(2) {
            margin-top: 50px;
            padding: 20px;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # Center the password box with columns
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        # Heading
        st.markdown("<h1 class='password-heading'>Change Password</h1>", unsafe_allow_html=True)

        # Grab the user's email from session
        email = st.session_state.get("user", "user@example.com")

        # Form elements with placeholder texts and icons for clarity
        st.markdown("<div class='custom-label'>Current Password</div>", unsafe_allow_html=True)
        current_password = st.text_input("Current Password", type="password", placeholder="🔒 Current Password",
                                         key="current_pwd", label_visibility="collapsed")
        st.markdown("<div class='custom-label'>New Password</div>", unsafe_allow_html=True)
        new_password = st.text_input("New Password", type="password", placeholder="🔒 New Password", key="new_pwd", label_visibility="collapsed")
        st.markdown("<div class='custom-label'>Confirm New Password</div>", unsafe_allow_html=True)
        confirm_password = st.text_input("Confirm New Password", type="password", placeholder="🔒 Confirm New Password",
                                         key="confirm_pwd", label_visibility="collapsed")
        change_button = st.button("Change Password", key="change_pwd_button", use_container_width=True)

        if change_button:
            if authenticate_user(email, current_password):
                if new_password == confirm_password:
                    update_password(email, new_password)
                    st.success("Password changed successfully!")
                    st.session_state["password_changed"] = True
                    st.rerun()
                else:
                    st.error("New passwords do not match!")
            else:
                st.error("Incorrect current password!")


# --- NEW FUNCTION: Autosave check ---
def maybe_autosave_chat():
    """Autosave the current chat if enough time has passed since last save."""
    current_time = time.time()

    # Initialize last_save_time if not present
    if "last_save_time" not in st.session_state:
        st.session_state.last_save_time = current_time
        return

    # Skip if no messages or if not enough time has passed
    if not st.session_state.chat_history or (current_time - st.session_state.last_save_time) < AUTOSAVE_INTERVAL:
        return

    # Avoid saving if the conversation hasn't changed
    if "last_saved_message_count" in st.session_state and len(
            st.session_state.chat_history) == st.session_state.last_saved_message_count:
        return

    # Save the current conversation with small tables
    save_chat_session_to_db(
        user=st.session_state["user"],
        messages=st.session_state.chat_history,
        persistent_dfs=st.session_state.persistent_dfs if "persistent_dfs" in st.session_state else [],
        chat_message_tables=st.session_state.chat_message_tables if "chat_message_tables" in st.session_state else {}
    )

    # Update last save time and message count
    st.session_state.last_save_time = current_time
    st.session_state.last_saved_message_count = len(st.session_state.chat_history)


def save_after_exchange():
    """Save the conversation immediately after each user-assistant exchange."""
    if not st.session_state.chat_history:
        return

    # Save the current conversation with small tables
    save_chat_session_to_db(
        user=st.session_state["user"],
        messages=st.session_state.chat_history,
        persistent_dfs=st.session_state.persistent_dfs if "persistent_dfs" in st.session_state else [],
        chat_message_tables=st.session_state.chat_message_tables if "chat_message_tables" in st.session_state else {}
    )

    # Update tracking variables
    st.session_state.last_save_time = time.time()
    st.session_state.last_saved_message_count = len(st.session_state.chat_history)


# --- MODIFIED save_chat_session_to_db ---
def save_chat_session_to_db(user, messages, persistent_dfs=None, chat_message_tables=None):
    """Save the current conversation to DB, storing small DataFrames (under 1000 rows) as JSON."""
    if not messages:
        return

    # Generate a better title from first user message (not system prompt)
    user_messages = [msg for msg in messages if msg["role"] == "user"]
    if user_messages:
        title = user_messages[0]["content"][:30] + "..."
    else:
        title = "New Chat (" + datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + ")"

    # Store small tables data
    small_tables = {}
    if persistent_dfs and chat_message_tables:
        for msg_idx, df_idx in chat_message_tables.items():
            if df_idx < len(persistent_dfs):
                df = persistent_dfs[df_idx]
                if len(df) <= 1000:  # Only store tables with 1000 rows or fewer
                    # Convert DataFrame to dict and store with message index as key
                    small_tables[str(msg_idx)] = {
                        'data': df.to_dict(orient='records'),
                        'columns': df.columns.tolist()
                    }

    messages_json = json.dumps(messages)
    small_tables_json = json.dumps(small_tables) if small_tables else "{}"
    df_mappings_json = json.dumps(chat_message_tables) if chat_message_tables else "{}"

    db_session = SessionLocal()
    try:
        # Check if we already have a chat with the same ID in session
        if "current_chat_id" in st.session_state:
            existing_chat = db_session.query(ChatHistory).filter(
                ChatHistory.id == st.session_state.current_chat_id).first()
            if existing_chat:
                existing_chat.title = title
                existing_chat.timestamp = datetime.datetime.now(timezone.utc)
                existing_chat.messages = messages_json
                existing_chat.persistent_df_paths = "[]"  # Empty array as JSON
                existing_chat.persistent_df_mappings = df_mappings_json
                existing_chat.small_tables_data = small_tables_json  # Save small tables
                db_session.commit()
                return

        # Create new chat record if no existing one
        chat_record = ChatHistory(
            user=user,
            title=title,
            timestamp=datetime.datetime.now(timezone.utc),
            messages=messages_json,
            persistent_df_paths="[]",  # Empty array as JSON
            persistent_df_mappings=df_mappings_json,
            small_tables_data=small_tables_json  # Save small tables
        )
        db_session.add(chat_record)
        db_session.commit()

        # Store the ID of this chat for future updates
        st.session_state.current_chat_id = chat_record.id
    except Exception as e:
        print(f"Error saving chat session: {e}")
    finally:
        db_session.close()


def load_chat_sessions_for_user(user_email):
    """Return a list of all conversation dicts for this user."""
    db_session = SessionLocal()
    sessions = []
    try:
        results = db_session.query(ChatHistory).filter(ChatHistory.user == user_email).all()
        for s in results:
            # Include small_tables_data in the returned sessions
            small_tables_data = {}
            if hasattr(s, 'small_tables_data') and s.small_tables_data:
                try:
                    small_tables_data = json.loads(s.small_tables_data)
                except:
                    small_tables_data = {}

            sessions.append({
                "id": s.id,
                "user": s.user,
                "title": s.title,
                "timestamp": s.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "messages": json.loads(s.messages),
                "persistent_df_paths": [],  # Empty list for compatibility
                "small_tables_data": small_tables_data
            })
    except Exception as e:
        print(f"Error loading chat sessions: {e}")
    finally:
        db_session.close()
    return sessions


# 5. MODIFY the load_conversation_into_session function
def load_conversation_into_session(conversation):
    """Load the chosen conversation into session_state so user can continue."""
    # Load the full conversation for context (used for generating responses)
    st.session_state.messages = conversation["messages"]
    # For display, filter out the system message
    st.session_state.chat_history = [msg for msg in conversation["messages"] if msg["role"] != "system"]

    # Initialize empty persistent_dfs
    st.session_state.persistent_dfs = []

    # Initialize empty chat_message_tables
    st.session_state.chat_message_tables = {}

    # Process small tables if available
    if "small_tables_data" in conversation and conversation["small_tables_data"]:
        small_tables = conversation["small_tables_data"]
        for msg_idx_str, table_data in small_tables.items():
            # Convert string key to integer
            msg_idx = int(msg_idx_str)

            # Create DataFrame from saved data
            if 'data' in table_data and 'columns' in table_data:
                df = pd.DataFrame(table_data['data'], columns=table_data['columns'])

                # Add to persistent_dfs
                df_idx = len(st.session_state.persistent_dfs)
                st.session_state.persistent_dfs.append(df)

                # Map to message
                st.session_state.chat_message_tables[msg_idx] = df_idx

    # Store the conversation ID so we can update it rather than create new ones
    st.session_state.current_chat_id = conversation["id"]
    st.session_state.last_saved_message_count = len(conversation["messages"])
    st.session_state.last_save_time = time.time()


def get_limited_conversation_history(messages, window_size=2, preserve_correction_context=False):
    """
    Get only the most recent conversation window for LLM context.
    window_size=2 means we keep only the last Q&A pair (1 user message + 1 assistant message)
    preserve_correction_context=True will look back further if we're in a correction flow
    """
    if not messages:
        return []

    # Filter out system messages as we'll add that separately
    non_system_messages = [msg for msg in messages if msg["role"] != "system"]

    # Check if we're in a correction/clarification flow
    if preserve_correction_context and len(non_system_messages) >= 2:
        # Check if the last assistant message is a spelling suggestion
        last_assistant_msg = None
        for msg in reversed(non_system_messages):
            if msg["role"] == "assistant":
                last_assistant_msg = msg
                break

        if last_assistant_msg and last_assistant_msg["content"] == "spelling_suggestions":
            # We're in a spelling correction flow - include more context
            # Look for the original question that led to this correction
            window_size = 4  # Include 2 Q&A pairs to maintain context

    # Return only the last 'window_size' messages
    return non_system_messages[-window_size:] if len(non_system_messages) > window_size else non_system_messages

# ---------------------------------------------
# 7. Query Logging (existing from your code)
# ---------------------------------------------
def sync_sqlite_to_snowflake():
    try:
        DATABASE_URL = "sqlite:///log.db"
        local_engine = create_engine(DATABASE_URL)
        table_name = "query_result"
        with local_engine.connect() as conn:
            df = pd.read_sql(f"SELECT * FROM {table_name} WHERE synced_to_snowflake = FALSE", conn)
        if df.empty:
            print("No new data to sync.")
            return
        SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
        SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
        private_key = get_private_key_str()
        SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE")
        SNOWFLAKE_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA")
        SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE")
        SNOWFLAKE_ROLE = os.getenv("SNOWFLAKE_ROLE")
        if not all([SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, private_key,
                    SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE]):
            print("Missing Snowflake credentials in environment variables.")
            return
        snowflake_engine = create_engine(URL(
            account=SNOWFLAKE_ACCOUNT,
            user=SNOWFLAKE_USER,
            private_key=private_key,
            database=SNOWFLAKE_DATABASE,
            schema=SNOWFLAKE_SCHEMA,
            warehouse=SNOWFLAKE_WAREHOUSE,
            role=SNOWFLAKE_ROLE
        ))
        snowflake_table_name = "Logtable"

        with snowflake_engine.connect() as conn:
            df.to_sql(
                name=snowflake_table_name,
                con=conn,
                if_exists='append',
                index=False,
                method='multi'
            )

            with local_engine.connect() as local_conn:
                for id in df['id']:
                    local_conn.execute(
                        text(f"UPDATE {table_name} SET synced_to_snowflake = TRUE WHERE id = :id"),
                        {"id": id}
                    )
                local_conn.commit()
    except Exception as e:
        print(f"Error syncing data to Snowflake: {e}")


def save_query_result(user_query, natural_language_response, result, sql_query, response_text,
                      tokens_first_call=None, tokens_second_call=None, total_tokens_used=None, error_message=None):
    db_session = SessionLocal()
    try:
        query_result = QueryResult(
            query=user_query,
            answer=str(natural_language_response) if natural_language_response else None,
            sfresult=str(result) if result else None,
            sqlquery=str(sql_query) if sql_query else None,
            raw_response=str(response_text),
            tokens_first_call=tokens_first_call,
            tokens_second_call=tokens_second_call,
            total_tokens_used=total_tokens_used,
            error_message=str(error_message) if error_message else None
        )
        db_session.add(query_result)
        db_session.commit()
        sync_sqlite_to_snowflake()
    except Exception as e:
        print(f"Error saving query and result to database: {e}")
    finally:
        db_session.close()


from typing import List, Dict
import re


def save_clarification_as_instruction(engine, user_email, clarification_text):
    """
    Save user clarification as an instruction in INSTRUCTIONS_NEW table
    """
    from sqlalchemy import text
    import uuid

    # Generate a UUID for the ID column
    instruction_id = str(uuid.uuid4())

    insert_sql = """
    INSERT INTO ATI_AI_USAGE.INSTRUCTIONS_NEW ("ID", "INSTRUCTION", "USERNAME", "DELETED")
    VALUES (:id, :instruction, :username, FALSE)
    """

    try:
        with engine.connect() as conn:
            conn.execute(text(insert_sql), {
                "id": instruction_id,
                "instruction": clarification_text,
                "username": user_email
            })
            conn.commit()
        return True
    except Exception as e:
        print(f"Error saving instruction: {e}")
        return False


def handle_simple_error_recovery(
        sql_query: str,
        result: any,
        schema_text: str,
        user_email: str,
        engine
) -> Dict:
    """
    Enhanced error recovery that first checks for spelling mistakes,
    then falls back to clarification if needed
    """
    # Check if we need error recovery
    needs_recovery = False

    if isinstance(result, dict) and "error" in result:
        needs_recovery = True
    elif isinstance(result, list) and len(result) == 0:
        needs_recovery = True
    elif isinstance(result, list) and len(result) == 1:
        row = result[0]
        if all(value is None for value in row.values()):
            needs_recovery = True

    if not needs_recovery:
        return {"needs_clarification": False, "needs_correction": False}

    # First, check for spelling mistakes in the database
    spelling_check = check_for_spelling_mistakes(sql_query, schema_text, engine)

    if spelling_check["has_suggestions"]:
        # We have spelling suggestions
        return {
            "needs_clarification": False,
            "needs_correction": True,
            "correction_suggestions": spelling_check,
            "original_sql": sql_query,
            "confirmed_correct": spelling_check.get("confirmed_correct", [])
        }

    # No spelling corrections found, try simple clarification
    filter_info = extract_all_filters_from_sql(sql_query)

    if not filter_info["filters"]:
        return {"needs_clarification": False, "needs_correction": False}

    return {
        "needs_clarification": True,
        "needs_correction": False,
        "filter_info": filter_info,
        "original_sql": sql_query
    }


def extract_all_filters_from_sql(sql_query: str) -> Dict[str, List[Dict]]:
    """
    Extract filter conditions from SQL query including IN, NOT IN, BETWEEN clauses
    """
    # Extract table name
    table_match = re.search(r'FROM\s+(\w+)', sql_query, re.IGNORECASE)
    table_name = table_match.group(1) if table_match else "Unknown"

    # Extract WHERE clause
    where_match = re.search(r'WHERE\s+(.*?)(?:GROUP\s+BY|ORDER\s+BY|LIMIT|$)', sql_query, re.IGNORECASE | re.DOTALL)
    if not where_match:
        return {"table": table_name, "filters": []}

    where_clause = where_match.group(1)
    filters = []

    # Handle NOT IN clauses first (before regular IN)
    not_in_pattern = r"(\w+)\s+NOT\s+IN\s*\((.*?)\)"
    for match in re.finditer(not_in_pattern, where_clause, re.IGNORECASE | re.DOTALL):
        column = match.group(1)
        values_str = match.group(2)
        value_pattern = r"'([^']+)'|\"([^\"]+)\""
        for value_match in re.finditer(value_pattern, values_str):
            value = value_match.group(1) or value_match.group(2)
            filters.append({
                "column": column,
                "operator": "NOT IN",
                "value": value,
                "type": "string"
            })

    # Remove NOT IN clauses to avoid reprocessing
    where_clause_no_not_in = re.sub(not_in_pattern, '', where_clause, flags=re.IGNORECASE | re.DOTALL)

    # Handle regular IN clauses
    in_pattern = r"(\w+)\s+IN\s*\((.*?)\)"
    for match in re.finditer(in_pattern, where_clause_no_not_in, re.IGNORECASE | re.DOTALL):
        column = match.group(1)
        values_str = match.group(2)
        value_pattern = r"'([^']+)'|\"([^\"]+)\""
        for value_match in re.finditer(value_pattern, values_str):
            value = value_match.group(1) or value_match.group(2)
            filters.append({
                "column": column,
                "operator": "IN",
                "value": value,
                "type": "string"
            })

    # Remove IN clauses to avoid reprocessing
    where_clause_no_in = re.sub(in_pattern, '', where_clause_no_not_in, flags=re.IGNORECASE | re.DOTALL)

    # Handle BETWEEN clauses
    between_patterns = [
        (r"(\w+)\s+BETWEEN\s*'([^']+)'\s*AND\s*'([^']+)'", "string"),
        (r"(\w+)\s+BETWEEN\s*\"([^\"]+)\"\s*AND\s*\"([^\"]+)\"", "string"),
        (r"(\w+)\s+BETWEEN\s*(\d+(?:\.\d+)?)\s*AND\s*(\d+(?:\.\d+)?)", "numeric")
    ]

    for pattern, filter_type in between_patterns:
        for match in re.finditer(pattern, where_clause_no_in, re.IGNORECASE):
            column = match.group(1)
            filters.append({
                "column": column,
                "operator": "BETWEEN",
                "value": match.group(2),
                "type": filter_type
            })
            filters.append({
                "column": column,
                "operator": "BETWEEN",
                "value": match.group(3),
                "type": filter_type
            })

    # Remove BETWEEN clauses
    for pattern, _ in between_patterns:
        where_clause_no_in = re.sub(pattern, '', where_clause_no_in, flags=re.IGNORECASE)

    # Handle other patterns
    patterns = [
        (r"(\w+)\s+(ILIKE|LIKE)\s*'%?([^%']+)%?'", "string"),
        (r"(\w+)\s+(ILIKE|LIKE)\s*\"%?([^%\"]+)%?\"", "string"),
        (r"(\w+)\s*=\s*'([^']+)'", "string"),
        (r"(\w+)\s*=\s*\"([^\"]+)\"", "string"),
        (r"(\w+)\s*(=|!=|<>|<=|>=|<|>)\s*(\d+(?:\.\d+)?)", "numeric"),
    ]

    for pattern, filter_type in patterns:
        for match in re.finditer(pattern, where_clause_no_in, re.IGNORECASE):
            if len(match.groups()) == 3:
                column, operator, value = match.groups()
            else:
                column, value = match.groups()
                operator = "="

            filters.append({
                "column": column,
                "operator": operator,
                "value": value.strip("'\""),
                "type": filter_type
            })

    return {
        "table": table_name,
        "filters": filters
    }


def check_for_spelling_mistakes(sql_query: str, schema_text: str, engine) -> Dict:
    """
    Check if the query has potential spelling mistakes by looking for similar values in the database
    Only suggests corrections if similar values are found - doesn't assume everything is wrong
    """
    # Extract filters from SQL
    filter_info = extract_all_filters_from_sql(sql_query)

    if not filter_info["filters"]:
        return {"has_suggestions": False}

    suggestions = []
    confirmed_correct = []

    # For each filter, check if there are similar values in the database
    for filter_item in filter_info["filters"]:
        column = filter_item["column"]
        value = filter_item["value"]
        table = filter_info["table"]

        # Skip numeric values and dates
        if value.isdigit() or re.match(r'^\d{4}-\d{2}-\d{2}', value):
            continue

        # First check if the exact value exists
        exact_check_query = f"""
        SELECT COUNT(*) 
        FROM {table}
        WHERE "{column}" = '{value.replace("'", "''")}'
        """

        try:
            with engine.connect() as conn:
                exact_result = conn.execute(text(exact_check_query))
                exact_count = exact_result.scalar()

                if exact_count > 0:
                    # Value exists exactly - it's correct
                    confirmed_correct.append(value)
                    continue
        except:
            pass

        # Generic fuzzy matching approach
        # First, try to use Snowflake's EDITDISTANCE if available
        try:
            similarity_query = f"""
            SELECT DISTINCT 
                "{column}",
                EDITDISTANCE(LOWER("{column}"), LOWER('{value.replace("'", "''")}')) as edit_dist
            FROM {table}
            WHERE "{column}" IS NOT NULL
            AND EDITDISTANCE(LOWER("{column}"), LOWER('{value.replace("'", "''")}')) <= GREATEST(3, LENGTH('{value.replace("'", "''")}') * 0.3)
            ORDER BY edit_dist, "{column}"
            LIMIT 5
            """

            with engine.connect() as conn:
                result = conn.execute(text(similarity_query))
                similar_values = [row[0] for row in result if row[0]]

                if similar_values:
                    suggestions.append({
                        "column": column,
                        "original_value": value,
                        "suggested_values": similar_values
                    })
        except:
            # Fallback: Use character-by-character comparison
            # This works universally regardless of the type of spelling mistake
            try:
                # Get all distinct values from the column
                all_values_query = f"""
                SELECT DISTINCT "{column}"
                FROM {table}
                WHERE "{column}" IS NOT NULL
                AND LENGTH("{column}") BETWEEN LENGTH('{value.replace("'", "''")}') - 5 
                    AND LENGTH('{value.replace("'", "''")}') + 5
                """

                with engine.connect() as conn:
                    result = conn.execute(text(all_values_query))
                    all_values = [row[0] for row in result if row[0]]

                    # Calculate similarity scores in Python
                    scored_values = []
                    value_lower = value.lower()

                    for db_value in all_values:
                        db_value_lower = db_value.lower()

                        # Simple similarity calculation
                        # 1. Length similarity
                        length_diff = abs(len(db_value) - len(value))

                        # 2. Character overlap
                        common_chars = sum(1 for c in value_lower if c in db_value_lower)

                        # 3. Sequential match score
                        seq_score = 0
                        for i in range(min(len(value_lower), len(db_value_lower))):
                            if value_lower[i] == db_value_lower[i]:
                                seq_score += 1

                        # 4. Word matching for multi-word values
                        value_words = set(value_lower.split())
                        db_words = set(db_value_lower.split())
                        word_matches = len(value_words.intersection(db_words))

                        # Combined score
                        if length_diff <= 3 and (common_chars > len(value) * 0.7 or word_matches > 0):
                            score = (seq_score * 2) + common_chars + (word_matches * 5) - length_diff
                            scored_values.append((db_value, score))

                    # Sort by score and take top 5
                    scored_values.sort(key=lambda x: x[1], reverse=True)
                    similar_values = [val[0] for val in scored_values[:5]]

                    if similar_values:
                        suggestions.append({
                            "column": column,
                            "original_value": value,
                            "suggested_values": similar_values
                        })
            except Exception as e:
                continue

    # Return both suggestions and confirmed correct values
    if suggestions:
        return {
            "has_suggestions": True,
            "suggestions": suggestions,
            "confirmed_correct": confirmed_correct
        }

    return {"has_suggestions": False}

def process_simple_clarification(clarifications: Dict[str, str], engine, user_email: str) -> List[str]:
    """
    Process clarifications and save them as instructions
    """
    saved_instructions = []

    for key, description in clarifications.items():
        if key == "table":
            instruction = f"Use table {description} when appropriate"
        else:
            # Extract value from key (format: "column:value")
            if ":" in key:
                _, value = key.split(":", 1)
                instruction = f"{value}: {description}"
            else:
                instruction = f"{key}: {description}"

        # Save to instructions table
        if save_clarification_as_instruction(engine, user_email, instruction):
            saved_instructions.append(instruction)

    return saved_instructions

def main_app():
    if "user" in st.session_state:
        # username = st.session_state["user"].split("@")[0]
        username = st.session_state["user"]

        st.markdown(
            f"""
            <style>
            /* Container aligned to the right, near the 'Deploy' button */
            .username-container {{
                display: flex;
                justify-content: flex-end;
                margin-top: -54px; /* Adjust as needed */
                margin-right: -5px; /* Adjust spacing from right edge */
            }}
            /* Black text, smaller size to match 'Deploy' */
            .black-text {{
                font-size: 16px;
                color: black;
                font-weight: 600;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }}
            </style>
            <div class="username-container">
                <div class="black-text">
                    Logged in as: {username}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    import re

    def display_query_corrections(correction_suggestions, original_query):
        """
        Create interactive UI for query corrections

        Args:
            correction_suggestions (dict): Suggestions for query corrections
            original_query (str): Original SQL query

        Returns:
            str or None: Corrected query if a suggestion is selected
        """
        # Create a container for corrections
        correction_container = st.container()

        with correction_container:
            st.warning("No results found. Did you mean:")

            # Track selected corrections
            selected_corrections = {}

            # Display corrections for each suggestion
            for i, suggestion in enumerate(correction_suggestions['suggestions']):
                st.write(f"In column '{suggestion['column']}', '{suggestion['original_value']}' might be incorrect.")

                # Create a selectbox for each suggestion
                selected_value = st.selectbox(
                    f"Select a correction for {suggestion['column']}",
                    ['Original Value'] + suggestion['suggested_values'],
                    key=f"correction_{i}"
                )

                # If a different value is selected, store it
                if selected_value != 'Original Value':
                    selected_corrections[suggestion['column']] = selected_value

            # Correction button
            if st.button("Apply Corrections"):
                # Create a corrected query
                corrected_query = original_query

                # Replace values in the query
                for column, new_value in selected_corrections.items():
                    # Use regex to replace the specific column's value
                    # Handles both quoted and unquoted column names
                    corrected_query = re.sub(
                        rf'("{column}"\s*=\s*[\'"]){suggestion["original_value"]}([\'"])',
                        rf'\1{new_value}\2',
                        corrected_query
                    )

                return corrected_query

        return None

    # Modify your existing query execution logic
    def execute_corrected_query(corrected_query):
        """
        Execute the corrected query

        Args:
            corrected_query (str): SQL query with corrections

        Returns:
            list or dict: Query results
        """
        try:
            # Your existing query execution logic
            result = query_snowflake(corrected_query, st.session_state["user"])
            return result
        except Exception as e:
            st.error(f"Error executing corrected query: {e}")
            return None

    def format_query_correction_response(correction_suggestions, original_query):
        """
        Format query correction suggestions into a user-friendly message

        Args:
            correction_suggestions (dict): Suggestions for query corrections
            original_query (str): Original SQL query

        Returns:
            str: Formatted suggestion message
        """
        # Start with a clear, informative header
        suggestion_message = "🔍 Query Correction Suggestions:\n\n"

        # Add details about each suggestion
        for suggestion in correction_suggestions['suggestions']:
            suggestion_message += f"• Column: *{suggestion['column']}*\n"
            suggestion_message += f"  Original Value: `{suggestion['original_value']}`\n"
            suggestion_message += f"  Possible Correct Values:\n"

            # List possible corrections
            for value in suggestion['suggested_values']:
                suggestion_message += f"    - {value}\n"

            suggestion_message += "\n"

        # Add a helpful footer
        suggestion_message += "**Tip:** Consider using one of the suggested values to improve your query results.\n\n"
        suggestion_message += f"*Original Query:* ```sql\n{original_query}\n```"

        return suggestion_message

    def create_correction_dataframe(correction_suggestions):
        """
        Create a DataFrame to display correction suggestions

        Args:
            correction_suggestions (dict): Suggestions for query corrections

        Returns:
            pandas.DataFrame: Formatted suggestions DataFrame
        """
        import pandas as pd

        # Prepare data for DataFrame
        correction_data = []
        for suggestion in correction_suggestions['suggestions']:
            for suggested_value in suggestion['suggested_values']:
                correction_data.append({
                    'Column': suggestion['column'],
                    'Original Value': suggestion['original_value'],
                    'Suggested Value': suggested_value
                })

        # Create DataFrame
        df = pd.DataFrame(correction_data)
        return df

    def load_all_instructions(engine):
        """
        Load ALL instructions from INSTRUCTIONS_NEW table as a shared knowledge base
        Only loads instructions where DELETED = FALSE
        """
        # Use quotes to preserve case in Snowflake
        query = """
        SELECT "INSTRUCTION" 
        FROM ATI_AI_USAGE.INSTRUCTIONS_NEW
        WHERE "DELETED" = FALSE
        ORDER BY "INSTRUCTION"
        """

        try:
            with engine.connect() as conn:
                result = pd.read_sql(query, conn)

            if result.empty:
                return []

            # The column might come back in different cases
            for col in result.columns:
                if col.upper() == 'INSTRUCTION':
                    return result[col].tolist()

            # If still not found, return empty
            print(f"Column INSTRUCTION not found. Available columns: {result.columns.tolist()}")
            return []

        except Exception as e:
            print(f"Error loading instructions: {e}")
            import traceback
            traceback.print_exc()
            return []

    def format_instructions_for_prompt(instructions):
        """
        Format instructions into a clear prompt section
        """
        if not instructions:
            return ""

        formatted = "\n\nSHARED KNOWLEDGE BASE INSTRUCTIONS (MUST FOLLOW):\n"
        for i, instruction in enumerate(instructions, 1):
            formatted += f"{i}. {instruction}\n"

        formatted += "\nIMPORTANT: These are community-defined rules that must be incorporated into every SQL query where applicable.\n"

        return formatted

    def enhance_system_prompt_with_instructions(base_prompt, instructions):
        """
        Enhance the system prompt by adding shared instructions
        """
        if not instructions:
            return base_prompt

        instruction_section = format_instructions_for_prompt(instructions)

        # Insert after schema_text placeholder
        if "{schema_text}" in base_prompt:
            enhanced_prompt = base_prompt.replace(
                "{schema_text}",
                "{schema_text}" + instruction_section
            )
        else:
            enhanced_prompt = base_prompt + instruction_section

        return enhanced_prompt
    def get_cached_schema_details(user_email):
        """Get schema details from cache or database"""
        cache_key = f"schema_{user_email}"

        # Check if schema is already in session state cache
        if cache_key in st.session_state:
            return st.session_state[cache_key]

        # If not in cache, retrieve from database
        schema_details = get_schema_details(user_email)

        # Check if we got a valid schema (not an error)
        if isinstance(schema_details, dict) and "error" not in schema_details:
            # Cache the result in session state
            st.session_state[cache_key] = schema_details

        return schema_details

    if "awaiting_simple_clarification" not in st.session_state:
        st.session_state.awaiting_simple_clarification = False
    if "spelling_just_corrected" not in st.session_state:
        st.session_state.spelling_just_corrected = False
    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None
    if "awaiting_correction_choice" not in st.session_state:
        st.session_state.awaiting_correction_choice = False
    if "correction_data" not in st.session_state:
        st.session_state.correction_data = {}
    if "simple_clarification_data" not in st.session_state:
        st.session_state.simple_clarification_data = {}
    if "pending_retry_prompt" not in st.session_state:
        st.session_state.pending_retry_prompt = None
    if "last_sql_query" not in st.session_state:
        st.session_state.last_sql_query = None
    if "awaiting_continuation_choice" not in st.session_state:
        st.session_state.awaiting_continuation_choice = False
    if "continuation_options" not in st.session_state:
        st.session_state.continuation_options = None
    if "total_tokens" not in st.session_state:
        st.session_state.total_tokens = 0
    if "persistent_dfs" not in st.session_state:
        st.session_state.persistent_dfs = []
    if "continuation_streak" not in st.session_state:
        st.session_state.continuation_streak = 0
    if "auto_continuation_mode" not in st.session_state:
        st.session_state.auto_continuation_mode = False
    if "last_continuation_tables" not in st.session_state:
        st.session_state.last_continuation_tables = None
    if "spelling_suggestions_display" not in st.session_state:
        st.session_state.spelling_suggestions_display = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.chat_history = []

    # ---- AUTOSAVE CHECK ----
    if AUTOSAVE_ENABLED:
        maybe_autosave_chat()

    # -------------------------------
    #  A) SIDEBAR: Show Chat History
    # -------------------------------
    def delete_chat_by_id(chat_id):
        db_session = SessionLocal()
        try:
            db_session.query(ChatHistory).filter(ChatHistory.id == chat_id).delete()
            db_session.commit()
        except Exception as e:
            st.error(f"Error deleting chat: {e}")
        finally:
            db_session.close()

    def delete_all_chats_for_user(user_email):
        db_session = SessionLocal()
        try:
            db_session.query(ChatHistory).filter(ChatHistory.user == user_email).delete()
            db_session.commit()
            return True
        except Exception as e:
            st.error(f"Error deleting all chats: {e}")
            return False
        finally:
            db_session.close()

    with st.sidebar:
        logo = Image.open("4Logo.png")  # Your logo file
        st.image(logo, width=400)
        st.markdown("## Your Chat History")

        # 1. Load all user's past conversations from DB
        user_email = st.session_state["user"]
        user_conversations = load_chat_sessions_for_user(user_email)

        # 2. Group conversations by date
        if user_conversations:
            # Sort conversations by timestamp (newest first)
            user_conversations.sort(key=lambda x: x['timestamp'], reverse=True)

            # Group conversations by date
            conversations_by_date = {}
            for conv in user_conversations:
                # Extract just the date part from the timestamp (format: YYYY-MM-DD)
                date = conv['timestamp'].split(' ')[0]
                if date not in conversations_by_date:
                    conversations_by_date[date] = []
                conversations_by_date[date].append(conv)

            # Display conversations grouped by date
            for date, convs in conversations_by_date.items():
                # Format date for display (e.g., "15-3-25" instead of "2025-03-15")
                display_date = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%d-%m-%y")

                # Create a date header with custom styling
                st.markdown(f"""
                <div style="background-color: #f0f2f6; padding: 5px; border-radius: 5px; margin-bottom: 5px;">
                    <span style="font-weight: bold; color: #1A237E;">{display_date}</span>
                </div>
                """, unsafe_allow_html=True)

                # Display conversations for this date
                for conv in convs:
                    # Just show the title without the timestamp since we're already grouped by date
                    button_label = conv['title']
                    # Create columns with better proportions
                    col1, col2 = st.columns([0.9, 0.1])
                    with col1:
                        if st.button(
                                button_label,
                                key=f"btn_{conv['id']}",
                                use_container_width=True
                        ):
                            load_conversation_into_session(conv)
                            st.rerun()
                    with col2:
                        if st.button(
                                "🗑",
                                key=f"delete_{conv['id']}",
                                help="Delete this chat"
                        ):
                            delete_chat_by_id(conv['id'])
                            st.rerun()

        st.write("---")
        # 3. New Chat button
        if st.button("🆕 New Chat"):
            # Save the current conversation (if any) with small tables
            if st.session_state.chat_history:
                save_chat_session_to_db(
                    user=st.session_state["user"],
                    messages=st.session_state.chat_history,
                    persistent_dfs=st.session_state.persistent_dfs if "persistent_dfs" in st.session_state else [],
                    chat_message_tables=st.session_state.chat_message_tables if "chat_message_tables" in st.session_state else {}
                )
            # Clear the active session
            st.session_state.pop("messages", None)
            st.session_state.pop("chat_history", None)
            st.session_state.pop("persistent_dfs", None)
            st.session_state.pop("chat_message_tables", None)
            st.session_state.pop("current_chat_id", None)
            st.session_state.pop("last_saved_message_count", None)

            # Reset auto-continuation state
            st.session_state.continuation_streak = 0
            st.session_state.auto_continuation_mode = False
            st.session_state.last_continuation_tables = None

            st.rerun()

        # Clear History button
        if st.button("🗑️ Clear All History"):
            if delete_all_chats_for_user(st.session_state["user"]):
                # Clear session state as well
                if "messages" in st.session_state:
                    del st.session_state.messages
                if "chat_history" in st.session_state:
                    del st.session_state.chat_history
                if "current_chat_id" in st.session_state:
                    del st.session_state.current_chat_id
                if "persistent_dfs" in st.session_state:
                    del st.session_state.persistent_dfs
                if "chat_message_tables" in st.session_state:
                    del st.session_state.chat_message_tables
                if "last_saved_message_count" in st.session_state:
                    del st.session_state.last_saved_message_count

                st.success("All chat history cleared!")
                st.rerun()
            else:
                st.error("Failed to clear chat history.")
        # Add this in sidebar after the Learning Stats button

        # 4. Logout button
        if st.button("Logout"):
            # Clear all session state variables related to chat and queries
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            # Reinitialize only the authentication state
            st.session_state["authenticated"] = False
            st.rerun()

        if "knowledge_base_instructions" in st.session_state and st.session_state.knowledge_base_instructions:
            with st.expander("📚 Knowledge Base"):
                st.markdown("*Shared instructions from all users:*")
                for i, instruction in enumerate(st.session_state.knowledge_base_instructions, 1):
                    st.markdown(f"{i}. {instruction}")

    # ----------------------------------
    #  B) MAIN: Chat interface
    # ----------------------------------
    st.markdown("""
        <style>
            div.streamlit-expanderHeader {
                font-weight: bold !important;
                font-size: 18px !important; /* Bigger and bolder */
                font-family: 'Arial', sans-serif !important; /* Clean, professional font */
                color: #1A237E !important; /* Dark blue for better visibility */
            }
            div[data-testid="stExpander"] {
                max-width: 500px; /* Adjust width */
                margin-left: 0; /* Align to left */
            }
        </style>
    """, unsafe_allow_html=True)

    # UI Components
    st.title("❄️ AI Data Assistant ❄️")
    st.caption("Ask me about your business analytics queries")

    # Expander with optimized size and font
    with st.expander("📝 Not sure what to ask? Click here for sample questions"):
        st.markdown("""
            <div style="
                background: linear-gradient(to right, #e0f7fa, #b2ebf2);
                border-radius: 10px;
                padding: 15px;">
                <ul style="margin-bottom: 5px;">
                    <li><b>Paid invoice summary details:</b> "Paid Invoice Summary"</li>
                    <li><b>Purchase order details:</b> "Fetch all details of home depot where goods are invoiced"</li>
                    <li><b>Vendor Info:</b> "Vendor Details"</li>
                    <li><b>Purchase requisition details:</b> "Give me a count of purchase requisition for the year 2025"</li>
                </ul>
                <p style="color: #00838f; font-size: 0.9em; margin-bottom: 0;">
                    If you're unsure what to ask, feel free to use the sample questions above or rephrase them to get the insights you need.
                </p>
            </div>
        """, unsafe_allow_html=True)

    def fetch_system_prompt_sections():
        """Fetch all active system prompt sections from Snowflake in order"""
        engine = get_snowflake_connection()
        query = """
        SELECT section_name, prompt_text 
        FROM system_prompt_new
        ORDER BY section_order ASC
        """

        with engine.connect() as conn:
            result = pd.read_sql(query, conn)

        if result.empty:
            raise ValueError("No system prompt sections found in database")

        # Combine all sections into one complete prompt
        combined_prompt = ""
        for _, row in result.iterrows():
            combined_prompt += row['prompt_text'] + "\n\n"

        return combined_prompt.strip()

    # Prepare the system prompt for your LLM
    schema_details = get_cached_schema_details(st.session_state["user"])
    if "error" in schema_details:
        st.error(schema_details["error"])
        st.stop()

    schema_text = ""
    for table, columns in schema_details.items():
        schema_text += f"Table: {table}\n"
        schema_text += "Columns:\n"
        for col, dtype in columns:
            schema_text += f"  - {col} (Data Type: {dtype})\n"
        schema_text += "\n"

    # ENHANCED CODE - REPLACE WITH THIS:
    combined_template = fetch_system_prompt_sections()

    # Load ALL instructions from the knowledge base
    engine = get_snowflake_connection()
    all_instructions = load_all_instructions(engine)

    # Enhance the template with instructions
    enhanced_template = enhance_system_prompt_with_instructions(
        combined_template,
        all_instructions
    )

    # Format with schema_text
    system_prompt = enhanced_template.format(
        schema_text=schema_text,
        user_email=st.session_state["user"]
    )

    # Store both in session state
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = system_prompt
        st.session_state.knowledge_base_instructions = all_instructions

        # Create chat_message_columns map to track which messages have tables
    if "chat_message_tables" not in st.session_state:
        st.session_state.chat_message_tables = {}

        # Initialize messages without system prompt
    if not st.session_state.messages:
        st.session_state.messages = []  # Don't include system prompt here
        st.session_state.chat_history = []

        # Function to make API calls with system prompt

    def get_groq_response_with_system(conversation_messages):
        """Prepends the system prompt to conversation messages and calls the API"""
        # Always prepend the system message to the conversation history
        full_messages = [{"role": "system", "content": st.session_state.system_prompt}] + conversation_messages

        # Call your existing implementation
        return get_groq_response(full_messages)

        # Function to handle table display based on row count

    def display_table_with_size_handling(df, message_index, df_idx):
        """
        Display table with appropriate handling based on row size:
        - For tables > 100,000 rows: Show only download button
        - For tables <= 100,000 rows: Show download button + AgGrid table
        - For tables > 1000 rows: Show warning about temporary availability
        - For tables <= 1000 rows: Display normally (these are saved in session)

        Parameters:
        - df: pandas DataFrame to display
        - message_index: Current message index for unique key generation
        - df_idx: DataFrame index in persistent store
        """
        # Always provide download option regardless of size
        csv = df.to_csv(index=False).encode("utf-8")

        # Check row count to determine display method and warnings
        num_rows = len(df)

        if num_rows > 1000:
            # Warning for large tables that won't be saved
            st.warning(
                "⚠️ **Download is only available now!** This data is too large to save with your chat history and won't be accessible for download after navigating away from this page.",
                icon="⚠️")

        st.download_button(
            label="Download Full Dataset as CSV",
            data=csv,
            file_name=f"query_result_{message_index}.csv",
            mime="text/csv",
            key=f"download_csv_{message_index}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        )

        if num_rows <= 10000:
            # For tables under the threshold, show interactive AgGrid
            gb = GridOptionsBuilder.from_dataframe(df)
            gb.configure_default_column(filter=True, sortable=True)
            gridOptions = gb.build()
            AgGrid(
                df,
                gridOptions=gridOptions,
                height=400,
                width='100%',
                key=f"grid_{message_index}_{df_idx}_{id(df)}",  # Unique key
                update_mode=GridUpdateMode.VALUE_CHANGED
            )

    # Display the chat history in proper order, with tables integrated
    message_index = 0
    for msg_idx, msg in enumerate(st.session_state.chat_history):
        with st.chat_message(msg["role"]):
            # Check if this is a spelling suggestion message
            if msg["content"] == "spelling_suggestions":
                # Try to get the display data, handle None case
                display_data = getattr(st.session_state, 'spelling_suggestions_display', None)

                if display_data:
                    # Show confirmed correct values if any
                    if display_data and display_data.get("confirmed_correct"):
                        st.success(
                            f"✅ These values are correct and exist in the database: **{', '.join(display_data['confirmed_correct'])}**")
                        st.markdown("")

                    # Show suggestions
                    if display_data.get("num_corrections", 0) > 1:
                        st.warning(
                            f"🔍 **I found potential spelling issues with {display_data['num_corrections']} value(s):**")
                    else:
                        st.markdown("🔍 **I found a potential spelling issue:**")

                    st.markdown("")

                    # Display the suggestions if they exist
                    if display_data.get("suggestions") and display_data["suggestions"].get("suggestions"):
                        for i, suggestion in enumerate(display_data["suggestions"]["suggestions"], 1):
                            st.markdown(
                                f"**{i}.** For **:red[{suggestion['original_value']}]** in column **:blue[{suggestion['column']}]**:")

                            for j, value in enumerate(suggestion['suggested_values'], 1):
                                display_num = f"{i}.{j}"
                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;**{display_num}** {value}")

                            st.markdown("")

                    if display_data.get("num_corrections", 0) > 1:
                        st.info(
                            "You can:\n- Type a number (e.g., '1.1') to correct that value\n- Type multiple numbers separated by commas (e.g., '1.1, 2.1')\n- Type a new query to start over")
                    else:
                        st.info("Type the number of your choice (e.g., 1.1) or type a new query")
                else:
                    # Fallback display if data is missing
                    st.markdown("🔍 Found potential spelling issues. (Details not available)")
            else:
                # Regular message display
                st.markdown(msg["content"])

            # Check if this message has a corresponding table to display
            if msg["role"] == "assistant" and message_index in st.session_state.chat_message_tables:
                df_idx = st.session_state.chat_message_tables[message_index]
                if df_idx < len(st.session_state.persistent_dfs):
                    df = st.session_state.persistent_dfs[df_idx]

                    # Only display if the dataframe is not empty
                    if not df.empty:
                        # Use our new function to handle display based on size
                        display_table_with_size_handling(df, message_index, df_idx)

        if msg["role"] == "assistant":
            message_index += 1

    def animated_progress_bar(container, message, progress_time=1.5):
        """Display an animated progress bar with a message."""
        with container:
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i in range(101):
                progress_bar.progress(i)
                status_text.markdown(
                    f"<div style='color:#3366ff; font-weight:bold;'>{message}</div>",
                    unsafe_allow_html=True
                )
                time.sleep(progress_time / 100)

                # Pause briefly after finishing animation
            time.sleep(0.3)
            # Clear out the contents
            progress_bar.empty()
            status_text.empty()

    def clean_llm_response(response: str) -> str:

        """
        Cleans up LLM responses for consistent display:
        - Removes markdown formatting like *, _, `
        - Fixes spacing after commas
        - Normalizes multiple spaces
        """
        cleaned = re.sub(r'[*_`]', '', response)
        cleaned = re.sub(r',(?=\S)', ', ', cleaned)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned)
        return cleaned.strip()

    def extract_ranking_criteria(sql_query: str) -> str:
        """
        Analyze SQL query to determine the ranking/sorting criteria
        Returns a human-readable description of the criteria
        """
        sql_upper = sql_query.upper()

        # Check ORDER BY clause
        order_by_match = re.search(r'ORDER\s+BY\s+([^;]+?)(?:DESC|ASC|LIMIT|$)', sql_upper, re.IGNORECASE)

        if order_by_match:
            order_clause = order_by_match.group(1).strip()

            # Common patterns
            if 'COUNT(' in order_clause:
                if 'DISTINCT' in order_clause:
                    # Extract what's being counted
                    count_match = re.search(r'COUNT\s*\(\s*DISTINCT\s+(\w+)', order_clause)
                    if count_match:
                        column = count_match.group(1).lower()
                        return f"based on the count of unique {column.replace('_', ' ')}s"
                else:
                    return "based on the total count"

            elif 'SUM(' in order_clause:
                sum_match = re.search(r'SUM\s*\(\s*(\w+)', order_clause)
                if sum_match:
                    column = sum_match.group(1).lower()
                    return f"based on the total {column.replace('_', ' ')}"

            elif 'MAX(' in order_clause:
                return "based on the maximum value"

            elif 'MIN(' in order_clause:
                return "based on the minimum value"

            elif 'AVG(' in order_clause:
                return "based on the average"

        # Check if there's a LIMIT without clear ordering (implies some kind of top/max query)
        if 'LIMIT' in sql_upper and 'GROUP BY' in sql_upper:
            return "based on the grouping and aggregation used"

        return ""
    def format_llm_response(text: str) -> str:
        """
        Formats LLM responses into clean HTML using preferred font and bold keys.
        Handles all 'Key: Value' lines dynamically.
        """
        import html

        lines = text.strip().split('\n')
        formatted_lines = []

        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                formatted_lines.append(
                    f"<div><strong>{html.escape(key.strip())}:</strong> {html.escape(value.strip())}</div>")
            else:
                formatted_lines.append(f"<div>{html.escape(line.strip())}</div>")

        html_output = f"""
        <div style="font-family: Arial, sans-serif; font-size: 16px; color: #333; line-height: 1.6; padding: 8px 0;">
            {''.join(formatted_lines)}
        </div>
        """
        return html_output

    st.markdown("""
        <style>
        @keyframes pulse {
            0% {
                transform: scale(1);
                opacity: 1;
            }
            50% {
                transform: scale(1.05);
                opacity: 0.7;
            }
            100% {
                transform: scale(1);
                opacity: 1;
            }
        }

        .thinking-animation {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            animation: pulse 2s ease-in-out infinite;
            font-size: 18px;
            font-weight: 600;
            margin: 20px 0;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }

        .processing-dots {
            display: inline-block;
            width: 80px;
            text-align: left;
        }

        .processing-dots::after {
            content: '';
            animation: dots 1.5s steps(4, end) infinite;
        }

        @keyframes dots {
            0% { content: ''; }
            25% { content: '.'; }
            50% { content: '..'; }
            75% { content: '...'; }
            100% { content: ''; }
        }

        .thinking-icon {
            display: inline-block;
            animation: spin 2s linear infinite;
            margin-right: 10px;
        }

        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        </style>
        """, unsafe_allow_html=True)

    if st.session_state.awaiting_simple_clarification and "simple_clarification_data" in st.session_state:
        with st.chat_message("assistant"):
            filter_info = st.session_state.simple_clarification_data.get("filter_info", {})

            # Display the clarification UI
            st.markdown(
                '''<div style="background-color:#f8fafc; border-radius:10px; padding:18px 20px 14px 20px; margin-bottom:18px; border:1px solid #e0e7ef; font-size:16px;">
                <span style="font-size:18px; font-weight:600; color:#f5a623; vertical-align:middle; margin-right:8px;">&#128712;</span>
                <span style="font-weight:600; color:#222;">I couldn't find any results for your query.</span><br><br>
                <span style="color:#222;">I searched with the following:</span><br>
                <ul style="margin:8px 0 8px 18px;">
            ''' +
                ''.join([f'<li><b>{i}. {filter_item["value"]}</b> in column <b>{filter_item["column"]}</b></li>' for
                         i, filter_item in enumerate(filter_info.get("filters", []), 1)]) +
                f'<li>Table used: <b>{filter_info.get("table", "Unknown")}</b></li>' +
                '''</ul>
                <div style="margin-top:10px; color:#333;">
                    Please clarify what each value represents. For example:<br>
                    <span style="color:#666; font-size:15px;">
                    &bull; "it is a project ID"<br>
                    &bull; "it is a vendor name"<br>
                    &bull; "it is a person's name"<br>
                    </span>
                    <br>
                    <div style="background-color:#e3f2fd; padding:10px; border-radius:5px; margin-top:10px;">
                        <b>Note:</b> Leave the text box empty and click Submit if the column I used is correct and the result is genuinely empty/zero.
                    </div>
                </div>
                </div>''', unsafe_allow_html=True)

            with st.form(key="simple_correction_form"):
                clarifications = {}

                # Create input fields for each filter
                for i, filter_item in enumerate(filter_info.get("filters", []), 1):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.markdown(f"{i}. **{filter_item['value']}**")
                    with col2:
                        clarification = st.text_input(
                            label=f"What is {filter_item['value']}?",
                            key=f"simple_clarification_{i}",
                            placeholder="Leave empty if column is correct",
                            label_visibility="collapsed"
                        )
                        if clarification:  # Only add if not empty
                            clarifications[f"{filter_item['column']}:{filter_item['value']}"] = clarification

                submitted = st.form_submit_button("Submit Clarifications", type="primary")
                # Store the original prompt to retry with new instructions
                original_prompt = st.session_state.simple_clarification_data.get("original_prompt", "")
                if submitted:
                    # Check if user left everything empty (meaning columns are correct)
                    if not clarifications:
                        # User confirmed the columns are correct - just show the original result
                        # Get the original SQL result that was 0/NULL
                        original_sql = st.session_state.simple_clarification_data.get("original_sql", "")

                        # Clear clarification state
                        st.session_state.awaiting_simple_clarification = False
                        st.session_state.simple_clarification_data = {}

                        # Add a message confirming the result
                        confirmation_msg = "I understand. The query was correct, and the result is genuinely empty/zero. This means there are no matching records for your search criteria."
                        st.session_state.messages.append({"role": "assistant", "content": confirmation_msg})
                        st.session_state.chat_history.append({"role": "assistant", "content": confirmation_msg})

                        save_after_exchange()
                        st.rerun()



                    else:

                        # User provided clarifications - but DON'T save yet

                        # Store clarifications temporarily

                        st.session_state.pending_clarifications = clarifications

                        st.session_state.pending_clarification_filters = filter_info.get("filters", [])

                        # Format clarifications into instructions for LLM

                        temp_instructions = []

                        for key, description in clarifications.items():

                            if ":" in key:

                                _, value = key.split(":", 1)

                                temp_instructions.append(f"{value}: {description}")

                            else:

                                temp_instructions.append(f"{key}: {description}")

                        # Store temporary instructions to be added to system prompt

                        st.session_state.temp_clarifications = temp_instructions

                        # Clear clarification state

                        st.session_state.awaiting_simple_clarification = False

                        st.session_state.simple_clarification_data = {}

                        # Add a message to chat history

                        clarification_msg = "I'll try your question again with this clarification..."

                        st.session_state.messages.append({"role": "assistant", "content": clarification_msg})

                        st.session_state.chat_history.append({"role": "assistant", "content": clarification_msg})

                        # Set a flag to automatically retry the question

                        st.session_state.pending_retry_prompt = original_prompt

                        # DON'T save to database yet - wait to see if spelling correction is needed

                        save_after_exchange()

                        st.rerun()

    elif st.session_state.pending_retry_prompt:  # Note the 'elif' here - this ensures it doesn't run when showing clarification UI
        retry_prompt = st.session_state.pending_retry_prompt
        st.session_state.pending_retry_prompt = None  # Clear it immediately to prevent duplicate execution

        # Show the retried question in chat
        with st.chat_message("user"):
            st.markdown(retry_prompt)

        # Add to history
        st.session_state.messages.append({"role": "user", "content": retry_prompt})
        st.session_state.chat_history.append({"role": "user", "content": retry_prompt})

        # Now process this prompt with the updated instructions
        # Create a placeholder for the initial loading animation
        initial_loading_placeholder = st.empty()

        # Show immediate loading animation
        with initial_loading_placeholder.container():
            st.markdown("""
                <div class="thinking-animation">
                    <span class="thinking-icon">🤔</span>
                    Reprocessing with clarifications<span class="processing-dots"></span>
                </div>
                """, unsafe_allow_html=True)

        # Store the original prompt for display purposes
        original_prompt = retry_prompt
        prompt = retry_prompt  # Set prompt variable for processing

        # Apply both contextual and synonym corrections
        engine = get_snowflake_connection()
        corrected_prompt, correction_info = correct_user_question_enhanced(
            retry_prompt,
            schema_text,
            engine,
            get_groq_response,
            conversation_history=st.session_state.messages
        )

        # Clear the initial loading animation
        initial_loading_placeholder.empty()

        # Determine which prompt to use
        final_prompt = corrected_prompt if correction_info.get('replacements') else original_prompt

        # If corrections were made, show them with more detail
        if correction_info.get('replacements'):
            info_text = "**Query Correction Applied:**\n\n"
            info_text += f"Original: {original_prompt}\n\n"
            info_text += f"Corrected: {corrected_prompt}\n\n"

            if correction_info.get('contextual_replacements'):
                info_text += "**Contextual replacements:**\n"
                for orig, repl in correction_info['contextual_replacements'].items():
                    info_text += f"- '{orig}' → '{repl}'\n"
            if correction_info.get('synonym_replacements'):
                info_text += "\n**Synonym replacements:**\n"
                for orig, repl in correction_info['synonym_replacements'].items():
                    info_text += f"- '{orig}' → '{repl}'\n"

            st.info(info_text, icon="ℹ️")

        # Use the corrected prompt for processing
        prompt = final_prompt

        # Continue with the rest of processing
        progress_container = st.container()
        response_container = st.container()
        final_message_placeholder = st.empty()

        sql_query = None
        response_text = None

        try:
            # 1. Analyzing phase
            animated_progress_bar(
                progress_container,
                "🔍 Re-analyzing your query with clarifications...",
                progress_time=1.0
            )

            # 2. SQL generation update
            with progress_container:
                status_text = st.empty()
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>💻 Generating SQL query with new understanding...</div>",
                    unsafe_allow_html=True
                )

            # If we have temporary clarifications, add them to the system prompt
            if hasattr(st.session_state, 'temp_clarifications') and st.session_state.temp_clarifications:
                # Get current system prompt
                current_system_prompt = st.session_state.system_prompt

                # Add clarifications
                clarification_text = "\n\nTEMPORARY CLARIFICATIONS FOR THIS QUERY:\n"
                for clarification in st.session_state.temp_clarifications:
                    clarification_text += f"- {clarification}\n"

                # Temporarily update system prompt
                enhanced_prompt = current_system_prompt + clarification_text

                # Create messages with enhanced system prompt
                enhanced_messages = [{"role": "system", "content": enhanced_prompt}] + st.session_state.messages[1:]

                # Use limited context for SQL generation
                # Check if we're in a correction flow
                in_correction_flow = st.session_state.get("spelling_just_corrected", False)
                limited_messages = get_limited_conversation_history(
                    enhanced_messages[1:],
                    window_size=2,
                    preserve_correction_context=in_correction_flow
                )
                enhanced_messages_limited = [{"role": "system", "content": enhanced_prompt}] + limited_messages
                response_text, token_usage_first_call = get_groq_response(enhanced_messages_limited)

                # Clear temporary clarifications after use
                del st.session_state.temp_clarifications
            else:
                # Use limited context for SQL generation
                # Check if we're in a correction flow
                in_correction_flow = st.session_state.get("spelling_just_corrected", False)
                limited_messages = get_limited_conversation_history(
                    st.session_state.messages,
                    window_size=2,
                    preserve_correction_context=in_correction_flow
                )
                response_text, token_usage_first_call = get_groq_response_with_system(limited_messages)

            st.session_state.total_tokens += token_usage_first_call

            # Check if it's an error response
            if response_text.strip().startswith("ERROR:"):
                raise Exception(response_text.strip())

            sql_query = response_text.strip()

            if sql_query.startswith("```sql"):
                sql_query = sql_query[6:]  # Remove ```sql
            if sql_query.startswith("```"):
                sql_query = sql_query[3:]  # Remove ```
            if sql_query.endswith("```"):
                sql_query = sql_query[:-3]  # Remove trailing ```

            sql_query = sql_query.strip()
            original_sql = sql_query
            sql_query = fix_generated_sql(sql_query, schema_text)
            st.session_state.last_sql_query = sql_query

            # 3. Executing query animation update
            with progress_container:
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>⚡ Executing corrected query on Snowflake...</div>",
                    unsafe_allow_html=True
                )

            # Execute the query directly
            result = query_snowflake(sql_query, st.session_state["user"])

            def get_snowflake_connectionz():
                return create_engine(URL(
                    account=os.getenv("SNOWFLAKE_ACCOUNT"),
                    user=os.getenv("SNOWFLAKE_USER"),
                    private_key=get_private_key_str(),
                    database=os.getenv("SNOWFLAKE_DATABASE"),
                    schema="AGENTAI",
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
                    role=os.getenv("SNOWFLAKE_ROLE")
                ))

            # Check if we need error recovery (including spelling check) after clarification
            engine = get_snowflake_connectionz()
            error_recovery = handle_simple_error_recovery(
                sql_query,
                result,
                schema_text,
                st.session_state["user"],
                engine
            )

            # Check if spelling was just corrected - if so, skip spelling check
            if hasattr(st.session_state, 'spelling_just_corrected') and st.session_state.spelling_just_corrected:
                # Clear the flag
                st.session_state.spelling_just_corrected = False

                # Don't run spelling check again - process as genuine empty result
                if isinstance(result, list) and len(result) == 0:
                    natural_response = "No results found. The query is correct but there's no matching data for this vendor in 2025."
                elif isinstance(result, list) and len(result) == 1:
                    row = result[0]
                    if all(value is None for value in row.values()):
                        natural_response = "The query returned NULL. There's no purchasing data for this vendor in 2025."
                else:
                    natural_response = "No data found for the specified criteria."

                # Skip spelling check and continue with normal flow
                error_recovery = {"needs_correction": False, "needs_clarification": False}

            if error_recovery.get("needs_correction"):
                # Clear any existing progress animations
                with progress_container:
                    if 'status_text' in locals():
                        status_text.empty()
                    progress_container.empty()

                if 'final_message_placeholder' in locals():
                    final_message_placeholder.empty()

                # Add a message explaining what happened
                clarification_note = "I applied your clarification, but found potential spelling issues:"

                # Show correction animation
                correction_animation = st.empty()
                with correction_animation.container():
                    st.markdown("""
                        <div class="thinking-animation" style="background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);">
                            <span class="thinking-icon">🔍</span>
                            Checking for spelling issues after clarification<span class="processing-dots"></span>
                        </div>
                        """, unsafe_allow_html=True)

                time.sleep(1.5)
                correction_animation.empty()

                # Display the spelling suggestions with clarification context
                with st.chat_message("assistant"):
                    st.info(clarification_note)

                    # Show the same spelling suggestion UI
                    display_data = {
                        "suggestions": error_recovery["correction_suggestions"],
                        "confirmed_correct": error_recovery.get("confirmed_correct", []),
                        "num_corrections": len(error_recovery["correction_suggestions"]["suggestions"]),
                        "suggestion_mapping": {}
                    }

                    # Build suggestion mapping
                    suggestion_counter = 1
                    for suggestion in error_recovery["correction_suggestions"]["suggestions"]:
                        st.markdown(
                            f"**{suggestion_counter}.** For **:red[{suggestion['original_value']}]** in column **:blue[{suggestion['column']}]**:")

                        for j, value in enumerate(suggestion['suggested_values'], 1):
                            display_num = f"{suggestion_counter}.{j}"
                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;**{display_num}** {value}")
                            display_data["suggestion_mapping"][display_num] = {
                                "original": suggestion['original_value'],
                                "replacement": value
                            }

                        st.markdown("")
                        suggestion_counter += 1

                    st.info("Type the number of your choice or type a new query")

                # Store state for spelling correction after clarification
                st.session_state.awaiting_correction_choice = True
                st.session_state.correction_data = {
                    "suggestions": error_recovery["correction_suggestions"],
                    "original_sql": error_recovery["original_sql"],
                    "original_prompt": retry_prompt,
                    "suggestion_mapping": display_data["suggestion_mapping"]
                }
                st.session_state.spelling_suggestions_display = display_data

                # Save the interaction
                text_response = "spelling_suggestions"
                st.session_state.messages.append({"role": "assistant", "content": text_response})
                st.session_state.chat_history.append({"role": "assistant", "content": text_response})

                save_after_exchange()
                st.rerun()

            # If no spelling issues, continue with normal result processing...

            # 4. Processing results
            with progress_container:
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>🔄 Processing results...</div>",
                    unsafe_allow_html=True
                )

            result_to_save = result
            if isinstance(result, list) and len(result) > 100:
                result_to_save = result[:100]

            if isinstance(result, dict) and "error" in result:
                natural_response = result["error"]
            elif isinstance(result, list):
                processed_result = []
                has_datetime = False
                if result and isinstance(result[0], dict):
                    for value in result[0].values():
                        if isinstance(value, (datetime.date, datetime.datetime)):
                            has_datetime = True
                            break

                if has_datetime:
                    for item in result:
                        processed_item = {}
                        for key, value in item.items():
                            if isinstance(value, (datetime.date, datetime.datetime)):
                                processed_item[key] = value.strftime('%Y-%m-%d')
                            else:
                                processed_item[key] = value
                        processed_result.append(processed_item)
                    df = pd.DataFrame(processed_result)
                else:
                    df = pd.DataFrame(result)

                df = df.drop_duplicates()
                num_rows = len(df)
                has_null_content = False
                if num_rows == 1:
                    if df.shape[1] == 1 and df.iloc[0, 0] is None:
                        has_null_content = True
                    elif isinstance(result, list) and len(result) == 1:
                        row = result[0]
                        if all(value is None for value in row.values()):
                            has_null_content = True

                if num_rows > 1:
                    df_idx = len(st.session_state.persistent_dfs)
                    st.session_state.persistent_dfs.append(df)
                    current_message_idx = len(
                        [m for m in st.session_state.chat_history if m["role"] == "assistant"]
                    )
                    st.session_state.chat_message_tables[current_message_idx] = df_idx
                    if num_rows > 10000:
                        natural_response = f"Query returned {num_rows:,} rows. Due to the large size of the result, only a download option is provided below. You can download the full dataset as a CSV file for viewing in your preferred spreadsheet application."
                    else:
                        natural_response = f"Query returned {num_rows:,} rows. The result is displayed below:"

                    token_usage_second_call = 0
                elif num_rows == 0 or has_null_content:
                    # Still no results - shouldn't happen after clarification, but handle gracefully
                    natural_response = "I still couldn't find results. The clarification has been saved and will be used for future queries."
                else:
                    # Single row result - process normally
                    result_for_messages = result
                    with progress_container:
                        if 'status_text' in locals():
                            status_text.empty()
                        status_text = st.empty()
                        status_text.markdown(
                            "<div style='color:#3366ff; font-weight:bold;'>✍️ Generating human-friendly response...</div>",
                            unsafe_allow_html=True
                        )
                    instructions = {
                        "role": "user",
                        "content": f"""      
                                User Question: {prompt}.        
                                Database Query Result: {result_for_messages}.        
                                Instructions:       
                                1. Directly use the database query result to answer the user's question.       
                                2. Generate a precise, well-structured response that directly answers the query.      
                                3. Ensure proper punctuation, spacing, and relevant insights without making assumptions.      
                                4. Do not include SQL or JSON in the response.      
                                5. Use chat history for follow-ups; if unclear, infer the last mentioned entity/metric.      
                                """
                    }
                    temp_messages = st.session_state.messages + [instructions]
                    natural_response, token_usage_second_call = get_groq_response_with_system(temp_messages)
                    st.session_state.total_tokens += token_usage_second_call
                    natural_response = clean_llm_response(natural_response)
                    with progress_container:
                        status_text.markdown(
                            "<div style='color:#3366ff; font-weight:bold;'>✨ Formatting results for display...</div>",
                            unsafe_allow_html=True
                        )
                        time.sleep(0.8)
            else:
                natural_response = "No valid result returned."

            # Clear everything in the progress container
            with progress_container:
                if 'status_text' in locals():
                    status_text.empty()
                progress_container.empty()

            final_message_placeholder.markdown(
                "<div style='color:#3366ff; font-weight:bold;'>🎬 Preparing your answer...</div>",
                unsafe_allow_html=True
            )

            save_query_result(
                prompt,
                natural_response,
                result_to_save,
                sql_query,
                response_text,
                tokens_first_call=token_usage_first_call,
                tokens_second_call=locals().get("token_usage_second_call", None),
                total_tokens_used=st.session_state.total_tokens
            )

            st.session_state.messages.append({"role": "assistant", "content": natural_response})
            st.session_state.chat_history.append({"role": "assistant", "content": natural_response})
            # If we have pending clarifications and got results, save them now
            if hasattr(st.session_state, 'pending_clarifications') and st.session_state.pending_clarifications:
                # Only save if we got actual results (not error/empty)
                if not (isinstance(result, dict) and "error" in result) and not (
                        isinstance(result, list) and len(result) == 0):
                    engine = get_snowflake_connection()
                    saved = process_simple_clarification(
                        st.session_state.pending_clarifications,
                        engine,
                        st.session_state["user"]
                    )

                    if saved:
                        # Clear pending clarifications
                        st.success(f"✅ Saved {len(saved)} clarification(s) for future use!")
                        del st.session_state.pending_clarifications
                        if hasattr(st.session_state, 'pending_clarification_filters'):
                            del st.session_state.pending_clarification_filters

                        # Reload instructions
                        all_instructions = load_all_instructions(engine)
                        st.session_state.knowledge_base_instructions = all_instructions
            if hasattr(st.session_state, 'temp_clarifications'):
                del st.session_state.temp_clarifications
            save_after_exchange()


            # Clear the final transition message
            final_message_placeholder.empty()

            # Show final answer in the response container
            with response_container:
                with st.chat_message("assistant"):
                    formatted_html = format_llm_response(natural_response)
                    st.markdown(formatted_html, unsafe_allow_html=True)


                    current_message_idx = len(
                        [m for m in st.session_state.chat_history if m["role"] == "assistant"]
                    ) - 1
                    if current_message_idx in st.session_state.chat_message_tables:
                        df_idx = st.session_state.chat_message_tables[current_message_idx]
                        if df_idx < len(st.session_state.persistent_dfs):
                            df = st.session_state.persistent_dfs[df_idx]
                            if not df.empty:
                                display_table_with_size_handling(df, current_message_idx, df_idx)

        except Exception as e:
            # If there's an error, clear the progress animation first
            with progress_container:
                if 'status_text' in locals():
                    status_text.empty()
                progress_container.empty()

            if 'final_message_placeholder' in locals():
                final_message_placeholder.empty()

            natural_response = f"Error during retry: {str(e)}"
            save_query_result(
                prompt,
                None,
                None,
                sql_query if 'sql_query' in locals() else None,
                response_text if 'response_text' in locals() else str(e),
                error_message=str(e),
                tokens_first_call=locals().get("token_usage_first_call", None),
                total_tokens_used=st.session_state.total_tokens
            )
            st.session_state.messages.append({"role": "assistant", "content": natural_response})
            st.session_state.chat_history.append({"role": "assistant", "content": natural_response})
            with response_container:
                with st.chat_message("assistant"):
                    st.markdown(natural_response)

    if prompt := st.chat_input("Type your business question here..."):
        # Handle correction choice first
        if hasattr(st.session_state, 'awaiting_correction_choice') and st.session_state.awaiting_correction_choice:
            prompt_lower = prompt.strip().lower()

            # Handle "all" command
            if prompt_lower == "all":
                original_prompt = st.session_state.correction_data["original_prompt"]
                corrected_prompt = original_prompt

                # Apply first suggestion for each spelling mistake
                for suggestion in st.session_state.correction_data["suggestions"]["suggestions"]:
                    if suggestion["suggested_values"]:
                        corrected_prompt = corrected_prompt.replace(
                            suggestion["original_value"],
                            suggestion["suggested_values"][0]
                        )

                # Clear state and continue
                st.session_state.awaiting_correction_choice = False
                del st.session_state.correction_data
                st.info(f"✅ Applied all first suggestions")

                # Preserve clarifications if they exist
                if hasattr(st.session_state, 'pending_clarifications') and st.session_state.pending_clarifications:
                    temp_instructions = []
                    for key, description in st.session_state.pending_clarifications.items():
                        if ":" in key:
                            _, value = key.split(":", 1)
                            temp_instructions.append(f"{value}: {description}")
                        else:
                            temp_instructions.append(f"{key}: {description}")
                    st.session_state.temp_clarifications = temp_instructions

                prompt = corrected_prompt

            # Handle multiple number selections (e.g., "1.1, 2.1")
            elif "," in prompt:
                selections = [s.strip() for s in prompt.split(",")]
                original_prompt = st.session_state.correction_data["original_prompt"]
                corrected_prompt = original_prompt

                for selection in selections:
                    if selection in st.session_state.correction_data.get("suggestion_mapping", {}):
                        mapping = st.session_state.correction_data["suggestion_mapping"][selection]
                        corrected_prompt = corrected_prompt.replace(
                            mapping["original"],
                            mapping["replacement"]
                        )

                # Clear state and continue
                st.session_state.awaiting_correction_choice = False
                del st.session_state.correction_data
                st.info(f"✅ Applied {len(selections)} corrections")

                # Preserve clarifications if they exist
                if hasattr(st.session_state, 'pending_clarifications') and st.session_state.pending_clarifications:
                    temp_instructions = []
                    for key, description in st.session_state.pending_clarifications.items():
                        if ":" in key:
                            _, value = key.split(":", 1)
                            temp_instructions.append(f"{value}: {description}")
                        else:
                            temp_instructions.append(f"{key}: {description}")
                    st.session_state.temp_clarifications = temp_instructions

                prompt = corrected_prompt

            # Handle single number selection
            elif re.match(r'^\d+\.\d+$', prompt.strip()):
                if prompt.strip() in st.session_state.correction_data.get("suggestion_mapping", {}):
                    mapping = st.session_state.correction_data["suggestion_mapping"][prompt.strip()]
                    original_prompt = st.session_state.correction_data["original_prompt"]
                    corrected_prompt = original_prompt.replace(
                        mapping["original"],
                        mapping["replacement"]
                    )

                    # Clear state and continue
                    st.session_state.awaiting_correction_choice = False
                    del st.session_state.correction_data
                    st.info(f"✅ Using: {mapping['replacement']}")

                    # SET FLAG to indicate spelling was just corrected
                    # SET FLAG to indicate spelling was just corrected
                    st.session_state.spelling_just_corrected = True
                    st.session_state.preserve_correction_context = True

                    # If we have pending clarifications, update them with correct spelling
                    if hasattr(st.session_state, 'pending_clarifications') and st.session_state.pending_clarifications:
                        updated_clarifications = {}
                        for key, description in st.session_state.pending_clarifications.items():
                            # Check if this clarification contains the misspelled value
                            if ":" in key:
                                col, value = key.split(":", 1)
                                if value == mapping["original"]:
                                    # Update with corrected spelling
                                    new_key = f"{col}:{mapping['replacement']}"
                                    updated_clarifications[new_key] = description
                                else:
                                    updated_clarifications[key] = description
                            else:
                                updated_clarifications[key] = description

                        st.session_state.pending_clarifications = updated_clarifications

                        # CRITICAL: Re-create temp_clarifications with updated values
                        temp_instructions = []
                        for key, description in updated_clarifications.items():
                            if ":" in key:
                                _, value = key.split(":", 1)
                                temp_instructions.append(f"{value}: {description}")
                            else:
                                temp_instructions.append(f"{key}: {description}")
                        st.session_state.temp_clarifications = temp_instructions

                    prompt = corrected_prompt

            else:
                # User typed something else, treat as new question
                st.session_state.awaiting_correction_choice = False
                if hasattr(st.session_state, 'correction_data'):
                    del st.session_state.correction_data

        # Create a placeholder for the initial loading animation
        initial_loading_placeholder = st.empty()

        # Show immediate loading animation
        with initial_loading_placeholder.container():
            st.markdown("""
                <div class="thinking-animation">
                    <span class="thinking-icon">🤔</span>
                    Processing your question<span class="processing-dots"></span>
                </div>
                """, unsafe_allow_html=True)

        # Check if we're waiting for a continuation choice
        # Handle continuation choice
        if st.session_state.awaiting_continuation_choice and st.session_state.continuation_options:
            # User is responding to continuation question
            if prompt.strip() in ["1", "2"]:
                # Get the selected question
                selected_question = st.session_state.continuation_options[prompt.strip()]

                # Track continuation streak
                if prompt.strip() == "2":
                    # User selected continuation
                    st.session_state.continuation_streak += 1
                    st.info(f"✅ Continuation applied (Streak: {st.session_state.continuation_streak})")

                    # Enable auto mode after 2 consecutive continuations
                    if st.session_state.continuation_streak >= 1:
                        st.session_state.auto_continuation_mode = True
                        st.success(
                            "🚀 **Auto-continuation mode activated!** Future related questions will automatically continue from previous context.")
                else:
                    # User selected standalone - reset streak and disable auto mode
                    st.session_state.continuation_streak = 0
                    st.session_state.auto_continuation_mode = False
                    st.session_state.last_continuation_tables = None
                    st.info("Standalone interpretation selected. Auto-continuation mode reset.")

                # Reset continuation state
                st.session_state.awaiting_continuation_choice = False
                st.session_state.continuation_options = None

                # Use the selected question as the actual prompt
                prompt = selected_question

                # Clear the loading animation and show info about the selection
                initial_loading_placeholder.empty()

                # IMPORTANT: Set a flag to skip continuation detection for this interaction
                skip_continuation_check = True
            else:
                # User typed something else, treat as new question
                st.session_state.awaiting_continuation_choice = False
                st.session_state.continuation_options = None
                # Reset streak when user types new question instead of choosing
                st.session_state.continuation_streak = 0
                st.session_state.auto_continuation_mode = False
                st.session_state.last_continuation_tables = None
                skip_continuation_check = False
        else:
            skip_continuation_check = False

        # Store the original prompt for display purposes
        original_prompt = prompt

        # Check for continuation BEFORE applying corrections
        # Check for continuation BEFORE applying corrections
        if st.session_state.messages and st.session_state.last_sql_query and not skip_continuation_check:
            # Update loading animation
            with initial_loading_placeholder.container():
                st.markdown("""
                    <div class="thinking-animation">
                        <span class="thinking-icon">🔍</span>
                        Checking for related questions<span class="processing-dots"></span>
                    </div>
                    """, unsafe_allow_html=True)

            # Check if we should auto-apply continuation
            should_auto_apply = st.session_state.auto_continuation_mode

            continuation_result = check_and_handle_continuation(
                prompt,
                st.session_state.messages,
                schema_text,
                get_groq_response_with_system,
                st.session_state.last_sql_query,
                auto_apply=should_auto_apply  # Pass the auto_apply flag
            )

            if continuation_result["is_continuation"]:
                # Check if tables changed - this breaks auto-continuation mode
                current_tables = continuation_result.get("common_tables", [])

                # If auto-apply was used
                if continuation_result.get("auto_applied"):
                    # Tables changed? Reset auto mode
                    if st.session_state.last_continuation_tables and \
                            set(current_tables) != set(st.session_state.last_continuation_tables):
                        st.session_state.auto_continuation_mode = False
                        st.session_state.continuation_streak = 0
                        st.session_state.last_continuation_tables = None
                        st.warning("⚠️ Table context changed. Auto-continuation mode disabled.")
                        # Show the continuation prompt since context changed
                        initial_loading_placeholder.empty()
                        with st.chat_message("user"):
                            st.markdown(original_prompt)
                        st.session_state.messages.append({"role": "user", "content": original_prompt})
                        st.session_state.chat_history.append({"role": "user", "content": original_prompt})

                        with st.chat_message("assistant"):
                            st.markdown(continuation_result["formatted_response"])

                        st.session_state.awaiting_continuation_choice = True
                        st.session_state.continuation_options = continuation_result["options"]
                        st.session_state.messages.append(
                            {"role": "assistant", "content": continuation_result["formatted_response"]})
                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": continuation_result["formatted_response"]})
                        save_after_exchange()
                        st.stop()
                    else:
                        # Auto-apply continuation
                        combined_question = continuation_result["combined_question"]
                        st.session_state.last_continuation_tables = current_tables

                        # Clear loading animation
                        initial_loading_placeholder.empty()

                        # Show what happened
                        with st.chat_message("user"):
                            st.markdown(original_prompt)

                        st.info(f"🤖 **Auto-continuation applied:**\n\n{combined_question}", icon="✨")

                        # Add both original and combined to history
                        st.session_state.messages.append({"role": "user", "content": combined_question})
                        st.session_state.chat_history.append({"role": "user", "content": combined_question})


                        # Use the combined question
                        prompt = combined_question
                        skip_continuation_check = True
                else:
                    # Manual continuation prompt (normal behavior)
                    st.session_state.last_continuation_tables = current_tables

                    # Clear loading animation
                    initial_loading_placeholder.empty()

                    # Show the original question in chat
                    with st.chat_message("user"):
                        st.markdown(original_prompt)

                    # Add to history
                    st.session_state.messages.append({"role": "user", "content": original_prompt})
                    st.session_state.chat_history.append({"role": "user", "content": original_prompt})

                    # Show continuation options
                    with st.chat_message("assistant"):
                        st.markdown(continuation_result["formatted_response"])

                    # Save state for next interaction
                    st.session_state.awaiting_continuation_choice = True
                    st.session_state.continuation_options = continuation_result["options"]

                    # Add assistant's response to history
                    st.session_state.messages.append(
                        {"role": "assistant", "content": continuation_result["formatted_response"]})
                    st.session_state.chat_history.append(
                        {"role": "assistant", "content": continuation_result["formatted_response"]})

                    # Save the conversation
                    save_after_exchange()

                    # Stop here and wait for user's choice
                    st.stop()

        # Update loading animation for synonym correction
        with initial_loading_placeholder.container():
            st.markdown("""
                <div class="thinking-animation">
                    <span class="thinking-icon">✨</span>
                    Optimizing your question<span class="processing-dots"></span>
                </div>
                """, unsafe_allow_html=True)

        # Apply both contextual and synonym corrections
        engine = get_snowflake_connection()
        corrected_prompt, correction_info = correct_user_question_enhanced(
            prompt,
            schema_text,
            engine,
            get_groq_response,
            conversation_history=st.session_state.messages
        )

        # Clear the initial loading animation
        initial_loading_placeholder.empty()

        # Determine which prompt to use
        final_prompt = corrected_prompt if correction_info.get('replacements') else original_prompt

        # Show the original question in the chat
        with st.chat_message("user"):
            st.markdown(original_prompt)

        # If corrections were made, show them with more detail
        if correction_info.get('replacements'):
            info_text = "**Query Correction Applied:**\n\n"
            info_text += f"Original: {original_prompt}\n\n"
            info_text += f"Corrected: {corrected_prompt}\n\n"

            # Show contextual replacements separately if any
            if correction_info.get('contextual_replacements'):
                info_text += "**Contextual replacements:**\n"
                for orig, repl in correction_info['contextual_replacements'].items():
                    info_text += f"- '{orig}' → '{repl}'\n"

            # Show synonym replacements if any
            if correction_info.get('synonym_replacements'):
                info_text += "\n**Synonym replacements:**\n"
                for orig, repl in correction_info['synonym_replacements'].items():
                    info_text += f"- '{orig}' → '{repl}'\n"

            st.info(info_text, icon="ℹ️")

        # IMPORTANT: Add the CORRECTED question to session state, not the original
        st.session_state.messages.append({"role": "user", "content": final_prompt})
        st.session_state.chat_history.append({"role": "user", "content": final_prompt})

        # Use the corrected prompt for ALL processing from here on
        prompt = final_prompt  # This ensures the corrected question is used everywhere below

        # Continue with the rest of your existing code...
        progress_container = st.container()
        response_container = st.container()
        final_message_placeholder = st.empty()

        sql_query = None
        response_text = None

        try:
            # 1. Analyzing phase
            animated_progress_bar(
                progress_container,
                "🔍 Analyzing your query...",
                progress_time=1.0
            )

            # 2. SQL generation update
            with progress_container:
                status_text = st.empty()
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>💻 Generating SQL query...</div>",
                    unsafe_allow_html=True
                )

            # Check if we have temporary clarifications that need to be included
            if hasattr(st.session_state, 'temp_clarifications') and st.session_state.temp_clarifications:
                # Get current system prompt
                current_system_prompt = st.session_state.system_prompt

                # Add clarifications
                clarification_text = "\n\nTEMPORARY CLARIFICATIONS FOR THIS QUERY:\n"
                for clarification in st.session_state.temp_clarifications:
                    clarification_text += f"- {clarification}\n"

                # Temporarily update system prompt
                enhanced_prompt = current_system_prompt + clarification_text

                # Create messages with enhanced system prompt
                enhanced_messages = [{"role": "system", "content": enhanced_prompt}] + st.session_state.messages[1:]

                # Use limited context for SQL generation
                # Check if we're in a correction flow or just made a correction choice
                in_correction_flow = (
                        st.session_state.get("spelling_just_corrected", False) or
                        st.session_state.get("awaiting_correction_choice", False)
                )
                limited_messages = get_limited_conversation_history(
                    enhanced_messages[1:],
                    window_size=2,
                    preserve_correction_context=in_correction_flow
                )
                enhanced_messages_limited = [{"role": "system", "content": enhanced_prompt}] + limited_messages
                response_text, token_usage_first_call = get_groq_response(enhanced_messages_limited)

                # Don't delete temp_clarifications here - keep them for potential spelling correction
            else:
                # Use limited context for SQL generation
                # Check if we're in a correction flow or just made a correction choice
                in_correction_flow = (
                        st.session_state.get("spelling_just_corrected", False) or
                        st.session_state.get("awaiting_correction_choice", False)
                )
                limited_messages = get_limited_conversation_history(
                    st.session_state.messages,
                    window_size=2,
                    preserve_correction_context=in_correction_flow
                )
                response_text, token_usage_first_call = get_groq_response_with_system(limited_messages)

            st.session_state.total_tokens += token_usage_first_call

            # Check if it's an error response
            if response_text.strip().startswith("ERROR:"):
                raise Exception(response_text.strip())

            # Clean the SQL query - remove markdown code blocks
            sql_query = response_text.strip()

            # Remove ```sql and ``` markers if present
            if sql_query.startswith("```sql"):
                sql_query = sql_query[6:]  # Remove ```sql
            if sql_query.startswith("```"):
                sql_query = sql_query[3:]  # Remove ```
            if sql_query.endswith("```"):
                sql_query = sql_query[:-3]  # Remove trailing ```

            # Final cleanup - strip any remaining whitespace
            sql_query = sql_query.strip()
            original_sql = sql_query
            sql_query = fix_generated_sql(sql_query, schema_text)
            st.session_state.last_sql_query = sql_query

            # 3. Executing query animation update
            with progress_container:
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>⚡ Executing query on Snowflake...</div>",
                    unsafe_allow_html=True
                )

            # Execute the query directly
            result = query_snowflake(sql_query, st.session_state["user"])
            if isinstance(result, dict) and "error" in result and "Access Denied" in result["error"]:
                # This is an access control error - DO NOT trigger clarification
                natural_response = result["error"]

                # Skip all error recovery mechanisms
                st.session_state.messages.append({"role": "assistant", "content": natural_response})
                st.session_state.chat_history.append({"role": "assistant", "content": natural_response})

                # Show the error in chat
                with st.chat_message("assistant"):
                    st.error(natural_response)

                save_after_exchange()
                st.rerun()

            def get_snowflake_connectionz():
                return create_engine(URL(
                    account=os.getenv("SNOWFLAKE_ACCOUNT"),
                    user=os.getenv("SNOWFLAKE_USER"),
                    private_key=get_private_key_str(),
                    database=os.getenv("SNOWFLAKE_DATABASE"),
                    schema="AGENTAI",
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
                    role=os.getenv("SNOWFLAKE_ROLE")
                ))
            engine = get_snowflake_connectionz()
            error_recovery = handle_simple_error_recovery(
                sql_query,
                result,
                schema_text,
                st.session_state["user"],
                engine
            )

            # Check if spelling was just corrected - if so, skip spelling check
            if hasattr(st.session_state, 'spelling_just_corrected') and st.session_state.spelling_just_corrected:
                # Clear the flag
                st.session_state.spelling_just_corrected = False

                # Don't run spelling check again - process as genuine empty result
                if isinstance(result, list) and len(result) == 0:
                    natural_response = "No results found. The query is correct but there's no matching data for this vendor in 2025."
                elif isinstance(result, list) and len(result) == 1:
                    row = result[0]
                    if all(value is None for value in row.values()):
                        natural_response = "The query returned NULL. There's no purchasing data for this vendor in 2025."
                else:
                    natural_response = "No data found for the specified criteria."

                # Skip spelling check and continue with normal flow
                error_recovery = {"needs_correction": False, "needs_clarification": False}

            if error_recovery.get("needs_correction"):
                # Handle spelling corrections first
                with progress_container:
                    if 'status_text' in locals():
                        status_text.empty()
                    progress_container.empty()

                if 'final_message_placeholder' in locals():
                    final_message_placeholder.empty()

                # Add animation for spelling correction
                correction_animation = st.empty()
                with correction_animation.container():
                    st.markdown("""
                        <div class="thinking-animation" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                            <span class="thinking-icon">🔍</span>
                            Checking for similar matches<span class="processing-dots"></span>
                        </div>
                        """, unsafe_allow_html=True)

                time.sleep(1.5)
                correction_animation.empty()

                # Format the correction suggestions
                correction_suggestions = error_recovery["correction_suggestions"]
                confirmed_correct = error_recovery.get("confirmed_correct", [])

                # Display with nice formatting
                with st.chat_message("assistant"):
                    # Show confirmed correct values if any
                    if confirmed_correct:
                        st.success(
                            f"✅ These values are correct and exist in the database: **{', '.join(confirmed_correct)}**")
                        st.markdown("")

                    # Check if we have corrections to suggest
                    num_corrections = len(correction_suggestions["suggestions"])

                    if num_corrections > 0:
                        if num_corrections > 1:
                            st.warning(f"🔍 **I found potential spelling issues with {num_corrections} value(s):**")
                        else:
                            st.markdown("🔍 **I found a potential spelling issue:**")

                        st.markdown("")  # Add space

                        suggestion_counter = 1
                        suggestion_mapping = {}

                        # Show suggestions
                        for i, suggestion in enumerate(correction_suggestions["suggestions"], 1):
                            st.markdown(
                                f"**{i}.** For **:red[{suggestion['original_value']}]** in column **:blue[{suggestion['column']}]**:")

                            for j, value in enumerate(suggestion['suggested_values'], 1):
                                display_num = f"{i}.{j}"
                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;**{display_num}** {value}")
                                suggestion_mapping[display_num] = {
                                    "original": suggestion['original_value'],
                                    "replacement": value,
                                    "suggestion_index": i - 1
                                }

                            st.markdown("")  # Add space between suggestions

                        if num_corrections > 1:
                            st.info(
                                "You can:\n- Type a number (e.g., '1.1') to correct that value\n- Type multiple numbers separated by commas (e.g., '1.1, 2.1')\n- Type a new query to start over")
                        else:
                            st.info("Type the number of your choice (e.g., 1.1) or type a new query")

                    # If no results were found but no spelling corrections either
                    if num_corrections == 0 and not confirmed_correct:
                        st.warning(
                            "No results found, but I couldn't find any spelling corrections either. The values might be correct but have no matching data.")

                # Store for next interaction
                st.session_state.awaiting_correction_choice = True
                st.session_state.correction_data = {
                    "suggestions": correction_suggestions,
                    "original_sql": error_recovery["original_sql"],
                    "original_prompt": prompt,
                    "suggestion_mapping": suggestion_mapping
                }

                # Save text version for history
                # Don't save a generic text response - save the actual formatted response
                # This ensures the suggestions are preserved in the chat history
                st.session_state.messages.append({"role": "assistant", "content": "spelling_suggestions"})
                st.session_state.chat_history.append({"role": "assistant", "content": "spelling_suggestions"})

                # Store the actual suggestions in a separate field
                st.session_state.spelling_suggestions_display = {
                    "suggestions": correction_suggestions,
                    "confirmed_correct": confirmed_correct,
                    "num_corrections": num_corrections,
                    "suggestion_mapping": suggestion_mapping
                }

                save_after_exchange()
                st.rerun()

            elif error_recovery["needs_clarification"]:
                # Clear any existing progress animations first
                with progress_container:
                    if 'status_text' in locals():
                        status_text.empty()
                    progress_container.empty()

                # Clear final message placeholder if exists
                if 'final_message_placeholder' in locals():
                    final_message_placeholder.empty()

                # Create a persistent animation placeholder that stays until rerun
                clarification_animation = st.empty()

                # Show the animation and KEEP IT VISIBLE
                with clarification_animation.container():
                    st.markdown("""
                                    <div class="thinking-animation" style="background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%);">
                                        <span class="thinking-icon">🔍</span>
                                        Analyzing query patterns<span class="processing-dots"></span>
                                    </div>
                                    """, unsafe_allow_html=True)

                # Brief pause
                time.sleep(1.5)

                # Update to second message but keep the container
                with clarification_animation.container():
                    st.markdown("""
                                    <div class="thinking-animation" style="background: linear-gradient(135deg, #4ECDC4 0%, #44A08D 100%);">
                                        <span class="thinking-icon">💡</span>
                                        I need some clarification to help you better<span class="processing-dots"></span>
                                    </div>
                                    """, unsafe_allow_html=True)

                # Store recovery data
                st.session_state.awaiting_simple_clarification = True
                st.session_state.simple_clarification_data = {
                    "filter_info": error_recovery["filter_info"],
                    "original_sql": error_recovery["original_sql"],
                    "original_prompt": prompt
                }

                # Save to query log
                save_query_result(
                    prompt,
                    "Clarification needed",
                    None,
                    sql_query,
                    response_text,
                    tokens_first_call=token_usage_first_call,
                    tokens_second_call=0,
                    total_tokens_used=st.session_state.total_tokens,
                    error_message="Awaiting user clarification"
                )

                save_after_exchange()

                # Small delay to ensure the animation is visible before rerun
                time.sleep(0.5)

                # NOW rerun - the animation will stay visible until the page actually refreshes
                st.rerun()

            # 4. Processing results
            with progress_container:
                status_text.markdown(
                    "<div style='color:#3366ff; font-weight:bold;'>🔄 Processing results...</div>",
                    unsafe_allow_html=True
                )

                # ----- Handle Results -----
            result_to_save = result
            if isinstance(result, list) and len(result) > 100:
                # Take a sample of 100 rows for saving to Snowflake
                result_to_save = result[:100]
            if isinstance(result, dict) and "error" in result:
                natural_response = result["error"]
            elif isinstance(result, list):
                # Pre-process data (datetime conversions, etc.)
                processed_result = []
                has_datetime = False
                if result and isinstance(result[0], dict):
                    for value in result[0].values():
                        if isinstance(value, (datetime.date, datetime.datetime)):
                            has_datetime = True
                            break

                if has_datetime:
                    for item in result:
                        processed_item = {}
                        for key, value in item.items():
                            if isinstance(value, (datetime.date, datetime.datetime)):
                                processed_item[key] = value.strftime('%Y-%m-%d')
                            else:
                                processed_item[key] = value
                        processed_result.append(processed_item)
                    df = pd.DataFrame(processed_result)
                else:
                    df = pd.DataFrame(result)

                df = df.drop_duplicates()
                num_rows = len(df)
                # First check if results exist but are essentially empty/null
                has_null_content = False
                if num_rows == 1:
                    # Check if we have a single row with NULL values
                    if df.shape[1] == 1 and df.iloc[0, 0] is None:
                        has_null_content = True
                    # For dictionaries like [{'TOTAL_COST': None}]
                    elif isinstance(result, list) and len(result) == 1:
                        row = result[0]
                        if all(value is None for value in row.values()):
                            has_null_content = True

                if num_rows > 1:
                    df_idx = len(st.session_state.persistent_dfs)
                    st.session_state.persistent_dfs.append(df)
                    current_message_idx = len(
                        [m for m in st.session_state.chat_history if m["role"] == "assistant"]
                    )
                    st.session_state.chat_message_tables[current_message_idx] = df_idx

                    # Customize message based on row count
                    if num_rows > 10000:
                        natural_response = f"Query returned {num_rows:,} rows. Due to the large size of the result, only a download option is provided below. You can download the full dataset as a CSV file for viewing in your preferred spreadsheet application."
                    else:
                        natural_response = f"Query returned {num_rows:,} rows. The result is displayed below:"

                    token_usage_second_call = 0

                else:
                    result_for_messages = result
                    with progress_container:
                        if 'status_text' in locals():
                            status_text.empty()
                        status_text = st.empty()
                        status_text.markdown(
                            "<div style='color:#3366ff; font-weight:bold;'>✍️ Generating human-friendly response...</div>",
                            unsafe_allow_html=True
                        )
                    ranking_criteria = ""
                    if any(keyword in prompt.lower() for keyword in
                           ['top', 'highest', 'most', 'maximum', 'best', 'largest', 'least', 'lowest', 'minimum']):
                        ranking_criteria = extract_ranking_criteria(sql_query)

                    instructions = {
                        "role": "user",
                        "content": f"""      
                                    User Question: {prompt}        
                                    Database Query Result: {result_for_messages}
                                    SQL Query Used: {sql_query}
                                    {f"Ranking Criteria: {ranking_criteria}" if ranking_criteria else ""}

                                    Instructions:       
                                    1. Directly use the database query result to answer the user's question.

                                    2. For ranking/top/maximum queries:
                                       - Always mention the criteria used for ranking
                                       - Use the "Ranking Criteria" provided above if available
                                       - Include the metric value if available in the result

                                    3. Format guidelines:
                                       - Use bullet points for better readability when there are many details
                                       - Bold important values like names, amounts, and dates
                                       - Keep monetary values properly formatted with commas

                                    4. Do not include raw SQL or JSON in the response

                                    5. Use chat history for context in follow-up questions

                                    Examples:
                                    - "Top vendor by purchase orders" → "The top vendor is X with Y purchase orders"
                                    - "Highest spending project" → "Project X has the highest spending of $Y"
                                    - "Most active department" → "Department X is most active based on transaction count"
                                    """
                    }
                    temp_messages = st.session_state.messages + [instructions]
                    natural_response, token_usage_second_call = get_groq_response_with_system(temp_messages)
                    st.session_state.total_tokens += token_usage_second_call
                    natural_response = clean_llm_response(natural_response)
                    with progress_container:
                        status_text.markdown(
                            "<div style='color:#3366ff; font-weight:bold;'>✨ Formatting results for display...</div>",
                            unsafe_allow_html=True
                        )
                        # Add a small delay so users can see this transition message
                        time.sleep(0.8)
            else:
                natural_response = "No valid result returned."

                # Clear everything in the progress container (removes bars plus text)
            with progress_container:
                # Clear any remaining status text
                if 'status_text' in locals():
                    status_text.empty()
                    # And clear the entire container just to be safe
                progress_container.empty()

                # Show final transition message just before displaying the answer
            final_message_placeholder.markdown(
                "<div style='color:#3366ff; font-weight:bold;'>🎬 Preparing your answer...</div>",
                unsafe_allow_html=True
            )

            # ----- Save Results & Display -----
            save_query_result(
                prompt,
                natural_response,
                result_to_save,
                sql_query,
                response_text,
                tokens_first_call=token_usage_first_call,
                tokens_second_call=locals().get("token_usage_second_call", None),
                total_tokens_used=st.session_state.total_tokens
            )

            st.session_state.messages.append({"role": "assistant", "content": natural_response})
            st.session_state.chat_history.append({"role": "assistant", "content": natural_response})

            if hasattr(st.session_state, 'temp_clarifications'):
                del st.session_state.temp_clarifications
            save_after_exchange()

            # Clear the final transition message right before showing the answer
            final_message_placeholder.empty()

            # Show final answer in the response container
            with response_container:
                with st.chat_message("assistant"):
                    formatted_html = format_llm_response(natural_response)
                    st.markdown(formatted_html, unsafe_allow_html=True)

                    current_message_idx = len(
                        [m for m in st.session_state.chat_history if m["role"] == "assistant"]
                    ) - 1
                    if current_message_idx in st.session_state.chat_message_tables:
                        df_idx = st.session_state.chat_message_tables[current_message_idx]
                        if df_idx < len(st.session_state.persistent_dfs):
                            df = st.session_state.persistent_dfs[df_idx]
                            if not df.empty:
                                # Use our new function for consistent display handling
                                display_table_with_size_handling(df, current_message_idx, df_idx)

                if hasattr(st.session_state, 'pending_clarifications') and st.session_state.pending_clarifications:
                    engine = get_snowflake_connection()
                    saved = process_simple_clarification(
                        st.session_state.pending_clarifications,
                        engine,
                        st.session_state["user"]
                    )

                    if saved:
                        # Get the corrected value for display
                        first_key = list(st.session_state.pending_clarifications.keys())[0]
                        if ':' in first_key:
                            corrected_value = first_key.split(':')[1]
                            st.success(f"Saved clarification with corrected spelling: {corrected_value}")

                        del st.session_state.pending_clarifications
                        if hasattr(st.session_state, 'pending_clarification_filters'):
                            del st.session_state.pending_clarification_filters


        except Exception as e:
            # If there's an error, clear the progress animation first
            with progress_container:
                # Clear any remaining status text
                if 'status_text' in locals():
                    status_text.empty()
                    # And clear the entire container just to be safe
                progress_container.empty()

                # Also clear the final message placeholder if it exists
            if 'final_message_placeholder' in locals():
                final_message_placeholder.empty()

            natural_response = f"Error: {str(e)}"
            save_query_result(
                prompt,
                None,
                None,
                sql_query if 'sql_query' in locals() else None,
                response_text if 'response_text' in locals() else str(e),
                error_message=str(e),
                tokens_first_call=locals().get("token_usage_first_call", None),
                total_tokens_used=st.session_state.total_tokens
            )
            st.session_state.messages.append({"role": "assistant", "content": natural_response})
            st.session_state.chat_history.append({"role": "assistant", "content": natural_response})
            with response_container:
                with st.chat_message("assistant"):
                    st.markdown(natural_response)


# ---------------------------------------------
# 9. Entry point
# ---------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if st.session_state["authenticated"]:
    if needs_password_change(st.session_state["user"]):
        password_change_page()
    else:
        main_app()
else:
    login_page()


