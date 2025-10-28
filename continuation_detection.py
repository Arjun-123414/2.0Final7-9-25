# continuation_detection.py
import re
import json
from typing import Dict, List, Tuple, Optional


def extract_table_from_query(sql_query: str) -> List[str]:
    """Extract table names from SQL query."""
    # Remove newlines and extra spaces
    sql_query = ' '.join(sql_query.split())

    # Common patterns to find table names
    patterns = [
        r'FROM\s+(\w+)',
        r'JOIN\s+(\w+)',
        r'INTO\s+(\w+)',
        r'UPDATE\s+(\w+)',
        r'TABLE\s+(\w+)'
    ]

    tables = []
    for pattern in patterns:
        matches = re.findall(pattern, sql_query, re.IGNORECASE)
        tables.extend(matches)

    # Remove duplicates and return
    return list(set(tables))


def is_sql_query(text: str) -> bool:
    """
    Check if the text is a SQL query rather than a natural language question.
    Returns True if SQL keywords are detected.
    """
    sql_keywords = [
        'SELECT', 'FROM', 'WHERE', 'JOIN', 'GROUP BY',
        'ORDER BY', 'LIMIT', 'INSERT', 'UPDATE', 'DELETE',
        'COUNT(', 'SUM(', 'AVG(', 'MAX(', 'MIN('
    ]

    text_upper = text.upper()

    # Check if multiple SQL keywords are present
    keyword_count = sum(1 for keyword in sql_keywords if keyword in text_upper)

    # If 2 or more SQL keywords found, it's likely SQL
    return keyword_count >= 2


def combine_questions_with_llm(current_question: str, previous_question: str, groq_response_func) -> str:
    """
    Use LLM to enhance current question using previous context,
    but DO NOT merge the two questions.
    """
    combination_prompt = f"""
    Your task is to rewrite the CURRENT question so that it is
    self-contained by inheriting only the necessary CONTEXT
    (like vendor id, year, filters) from the PREVIOUS question.

    ⚠️ VERY IMPORTANT RULES:
    - DO NOT repeat or include the actual intent of the previous question.
    - Only add missing details (vendor, year, department, etc.) from the previous question.
    - Focus ONLY on the CURRENT question intent.
    - The output must be a single, natural, complete question.
    - NEVER return SQL code - only natural language questions.

    Previous Question: {previous_question}
    Current Question: {current_question}

    Example 1:
    - Previous: "Show me sales data for Q1 2023"
    - Current: "Which month had highest sales"
    - Enhanced: "Which month had highest sales in Q1 2023?"

    Example 2:
    - Previous: "What are the employees in the marketing department"
    - Current: "Who has the highest salary"
    - Enhanced: "Who has the highest salary in the marketing department?"

    Example 3:
    - Previous: "no. of POs created in October 2025"
    - Current: "in company ATI"
    - Enhanced: "Number of POs created in October 2025 for company ATI?"

    Respond ONLY with the rewritten current question in natural language.
    DO NOT include any SQL code in your response.
    """

    messages = [
        {"role": "system",
         "content": "You are an expert at rewriting questions with inherited context. You ONLY return natural language questions, never SQL code."},
        {"role": "user", "content": combination_prompt}
    ]

    try:
        response, _ = groq_response_func(messages)
        cleaned_response = response.strip().strip('"').strip("'")

        # Validate that the response is not SQL
        if is_sql_query(cleaned_response):
            # Fallback to simple concatenation if LLM returns SQL
            return f"{current_question} (in context of: {previous_question})"

        return cleaned_response
    except Exception:
        return f"{current_question} (in context of: {previous_question})"


def detect_continuation_question(
        current_question: str,
        previous_question: str,
        previous_sql: str,
        current_sql: str,
        schema_text: str,
        groq_response_func
) -> Tuple[bool, Optional[str], Optional[str], Optional[List[str]]]:
    """
    Detect if current question is a continuation of previous question.
    Returns: (is_continuation, suggested_combined_question, explanation, common_tables)
    """

    # Extract tables from both queries
    prev_tables = extract_table_from_query(previous_sql)
    curr_tables = extract_table_from_query(current_sql)

    # If they don't use the same table, it's not a continuation
    if not prev_tables or not curr_tables:
        return False, None, None, None

    # Check if there's table overlap
    common_tables = set(prev_tables) & set(curr_tables)
    if not common_tables:
        return False, None, None, None

    # Use LLM to analyze if this is a continuation
    analysis_prompt = f"""
    Analyze if Question 2 is a continuation or follow-up of Question 1.

    Question 1: {previous_question}
    Question 2: {current_question}

    Common tables used: {', '.join(common_tables)}

    Rules for continuation detection:
    1. Both questions must use the same table(s)
    2. Question 2 should be asking for additional details or filtering of Question 1's context
    3. Question 2 might use pronouns (it, that, which) or be incomplete without Question 1's context
    4. Question 2 might be asking for a subset, maximum, minimum, or specific detail from Question 1's scope
    5. 🚫 IMPORTANT: Never merge intents. The combined_question must ONLY rewrite Question 2 by inheriting context (filters, vendor, year, etc.) from Question 1. Do not repeat or include Q1's intent.
    6. ⚠️ CRITICAL: The combined_question field must ALWAYS be a natural language question, NEVER SQL code.

    Examples of CORRECT combined_question format:
    - "Number of POs created in October 2025 for company ATI"
    - "Which month had highest sales in Q1 2023"
    - "Who has the highest salary in the marketing department"

    Examples of INCORRECT combined_question format (DO NOT DO THIS):
    - "SELECT COUNT(*) FROM..." 
    - Any SQL query

    Respond in JSON format:
    {{
        "is_continuation": true/false,
        "confidence": "high"/"medium"/"low",
        "reasoning": "brief explanation",
        "combined_question": "natural language question only, never SQL code"
    }}
    """

    messages = [
        {"role": "system",
         "content": "You are an expert at analyzing questions. When providing a combined_question, you ALWAYS use natural language, NEVER SQL code."},
        {"role": "user", "content": analysis_prompt}
    ]

    response, _ = groq_response_func(messages)

    try:
        # Strip markdown backticks if present
        cleaned_response = response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]

        result = json.loads(cleaned_response.strip())

        if result.get('is_continuation') and result.get('confidence') in ['high', 'medium']:
            combined_question = result.get('combined_question')

            # CRITICAL VALIDATION: Check if the combined_question is SQL
            if combined_question and is_sql_query(combined_question):
                # LLM returned SQL - use the dedicated combine function instead
                combined_question = combine_questions_with_llm(
                    current_question,
                    previous_question,
                    groq_response_func
                )

            return True, combined_question, result.get('reasoning'), list(common_tables)

    except Exception as e:
        # Fallback to simple heuristic if LLM fails
        continuation_keywords = ['which', 'what', 'that', 'those', 'maximum', 'minimum', 'most', 'least', 'highest',
                                 'lowest', 'in', 'for', 'of', 'from']
        current_lower = current_question.lower()

        # Check for continuation indicators
        has_continuation_word = any(word in current_lower for word in continuation_keywords)
        missing_context = len(current_question.split()) < 8  # Short questions often lack context

        if has_continuation_word and missing_context and common_tables:
            # Use LLM mechanism to combine questions meaningfully
            combined = combine_questions_with_llm(current_question, previous_question, groq_response_func)
            return True, combined, "Question appears to reference previous context", list(common_tables)

    return False, None, None, None


def format_continuation_options(
        original_question: str,
        combined_question: str,
        previous_question: str
) -> str:
    """Format the options for user to choose from."""

    formatted_response = f"""
🔄 **Continuation Question Detected**

I noticed your current question might be related to your previous question about: *"{previous_question}"*

Please select which interpretation you meant:

**1)** {original_question} *(interpret as standalone question)*

**2)** {combined_question} *(interpret as continuation of previous question)*

Type **1** or **2** to select your preferred interpretation, or rephrase your question if neither is correct.
"""

    return formatted_response


def handle_continuation_detection(
        current_question: str,
        chat_history: List[Dict],
        schema_text: str,
        groq_response_func,
        get_last_sql_query_func,
        auto_apply: bool = False
) -> Dict:
    """
    Main function to handle continuation detection.
    Returns dict with detection results and formatted response.

    Args:
        auto_apply: If True, automatically applies continuation without prompting user
    """

    # Find the last user question and its SQL
    previous_user_question = None
    previous_sql = None

    # Get last user message (excluding current)
    for msg in reversed(chat_history[:-1]):  # Exclude current message
        if msg["role"] == "user":
            previous_user_question = msg["content"]
            break

    if not previous_user_question:
        return {
            "is_continuation": False,
            "formatted_response": None,
            "options": None
        }

    # Get the SQL for previous question
    previous_sql = get_last_sql_query_func()

    if not previous_sql:
        return {
            "is_continuation": False,
            "formatted_response": None,
            "options": None
        }

    # Generate SQL for current question first
    current_sql_response, _ = groq_response_func(chat_history)
    current_sql = current_sql_response.strip()

    # Clean SQL
    if current_sql.startswith("```sql"):
        current_sql = current_sql[6:]
    if current_sql.startswith("```"):
        current_sql = current_sql[3:]
    if current_sql.endswith("```"):
        current_sql = current_sql[:-3]
    current_sql = current_sql.strip()

    # Detect continuation
    is_continuation, combined_question, reasoning, common_tables = detect_continuation_question(
        current_question,
        previous_user_question,
        previous_sql,
        current_sql,
        schema_text,
        groq_response_func
    )

    if is_continuation and combined_question:
        # Final validation before displaying
        if is_sql_query(combined_question):
            # Last resort - use simple concatenation
            combined_question = f"{current_question} (continuing from: {previous_user_question})"

        # If auto_apply is True, skip the prompt and directly use combined question
        if auto_apply:
            return {
                "is_continuation": True,
                "formatted_response": None,  # No prompt needed
                "options": None,  # No options needed
                "auto_applied": True,
                "combined_question": combined_question,
                "original_sql": current_sql,
                "reasoning": reasoning,
                "common_tables": common_tables
            }

        formatted_response = format_continuation_options(
            current_question,
            combined_question,
            previous_user_question
        )

        return {
            "is_continuation": True,
            "formatted_response": formatted_response,
            "options": {
                "1": current_question,
                "2": combined_question
            },
            "original_sql": current_sql,
            "reasoning": reasoning,
            "common_tables": common_tables,
            "auto_applied": False
        }

    return {
        "is_continuation": False,
        "formatted_response": None,
        "options": None,
        "common_tables": None
    }


# Integration function for your main.py
def check_and_handle_continuation(
        user_input: str,
        messages: List[Dict],
        schema_text: str,
        groq_response_func,
        last_sql_query: str = None,
        auto_apply: bool = False
) -> Dict:
    """
    Integration function to be called from your main application.

    Args:
        user_input: Current user question
        messages: Chat history
        schema_text: Database schema information
        groq_response_func: Your groq response function
        last_sql_query: The SQL query from the previous question
        auto_apply: If True, automatically applies continuation without prompting

    Returns:
        Dictionary with continuation detection results
    """

    # Create a function to return the last SQL query
    def get_last_sql():
        return last_sql_query

    # Add current question to a copy of messages for analysis
    temp_messages = messages.copy()
    temp_messages.append({"role": "user", "content": user_input})

    result = handle_continuation_detection(
        user_input,
        temp_messages,
        schema_text,
        groq_response_func,
        get_last_sql,
        auto_apply=auto_apply
    )

    return result
