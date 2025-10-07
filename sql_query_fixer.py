# sql_query_fixer.py
import re
from typing import Dict, List, Tuple


def extract_schema_info(schema_text: str) -> Dict[str, Dict[str, str]]:
    """
    Parse schema text to extract table and column information with data types.
    Returns: {table_name: {column_name: data_type}}
    """
    schema_dict = {}
    current_table = None

    lines = schema_text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('Table:'):
            current_table = line.replace('Table:', '').strip()
            schema_dict[current_table] = {}
        elif line.startswith('- ') and current_table:
            # Parse column info: "- column_name (Data Type: type)"
            match = re.match(r'- (\w+)\s*\(Data Type:\s*([^)]+)\)', line)
            if match:
                column_name = match.group(1)
                data_type = match.group(2).strip()
                schema_dict[current_table][column_name] = data_type

    return schema_dict


def is_string_type(data_type: str) -> bool:
    """Check if a data type is string-based."""
    string_types = ['VARCHAR', 'STRING', 'TEXT', 'CHAR', 'NVARCHAR', 'NCHAR']
    return any(st in data_type.upper() for st in string_types)


def fix_count_distinct(query: str) -> str:
    """
    Fix COUNT() to COUNT(DISTINCT) where appropriate.
    Handles cases like COUNT(column) -> COUNT(DISTINCT column)
    """
    # Pattern to find COUNT(column) but not COUNT(DISTINCT column) or COUNT(*)
    pattern = r'COUNT\s*\(\s*(?!DISTINCT\s+)(?!\*\s*)(\w+)\s*\)'

    def replace_with_distinct(match):
        column = match.group(1)
        return f'COUNT(DISTINCT {column})'

    fixed_query = re.sub(pattern, replace_with_distinct, query, flags=re.IGNORECASE)
    return fixed_query


def fix_string_comparisons(query: str, schema_dict: Dict[str, Dict[str, str]]) -> str:
    """
    Fix string column comparisons to use ILIKE instead of =
    """
    # Extract table names from query
    tables = []
    table_pattern = r'FROM\s+(\w+)|JOIN\s+(\w+)'
    for match in re.finditer(table_pattern, query, re.IGNORECASE):
        table = match.group(1) or match.group(2)
        if table:
            tables.append(table.upper())

    if not tables:
        return query

    # Find all string columns from the tables in the query
    string_columns = set()
    for table in tables:
        # Check both uppercase and original case
        for table_case in [table, table.lower(), table.upper()]:
            if table_case in schema_dict:
                for col, dtype in schema_dict[table_case].items():
                    if is_string_type(dtype):
                        string_columns.add(col.upper())
                break

    # Pattern to find column = 'value' comparisons
    # This handles both quoted and unquoted column names
    pattern = r'(?:")?(\w+)(?:")?\s*=\s*[\'"]([^\'\"]+)[\'"]'

    def replace_with_ilike(match):
        column = match.group(1)
        value = match.group(2)

        # Check if this column is a string column
        if column.upper() in string_columns:
            # Handle quoted column names
            if '"' in match.group(0):
                return f'"{column}" ILIKE \'%{value}%\''
            else:
                return f'{column} ILIKE \'%{value}%\''
        else:
            # Keep original if not a string column
            return match.group(0)

    fixed_query = re.sub(pattern, replace_with_ilike, query)

    return fixed_query


def fix_null_in_grouped_columns(query: str) -> str:
    """
    Add IS NOT NULL conditions for columns in GROUP BY when query has LIMIT and ORDER BY.
    This prevents NULL values from appearing as top results in "Which/What" queries.
    """
    # Check if query has both GROUP BY and LIMIT (common pattern for "which X has most Y" questions)
    if not (re.search(r'\bGROUP\s+BY\b', query, re.IGNORECASE) and
            re.search(r'\bLIMIT\s+\d+', query, re.IGNORECASE)):
        return query

    # Extract GROUP BY columns
    group_by_match = re.search(r'GROUP\s+BY\s+([\w\s,."]+?)(?:ORDER|LIMIT|HAVING|$)', query, re.IGNORECASE)
    if not group_by_match:
        return query

    group_by_columns = []
    group_by_text = group_by_match.group(1).strip()

    # Parse columns (handles both quoted and unquoted)
    for col in group_by_text.split(','):
        col = col.strip()
        # Remove quotes if present
        col_clean = col.strip('"')
        group_by_columns.append((col, col_clean))

    if not group_by_columns:
        return query

    # Check if WHERE clause exists
    where_match = re.search(r'\bWHERE\b(.*?)(?:GROUP|ORDER|$)', query, re.IGNORECASE | re.DOTALL)

    # Build NOT NULL conditions
    not_null_conditions = []
    for col_original, col_clean in group_by_columns:
        # Skip if already has a NOT NULL check for this column
        if where_match and f'{col_clean} IS NOT NULL' in where_match.group(1).upper():
            continue
        not_null_conditions.append(f'{col_original} IS NOT NULL')

    if not not_null_conditions:
        return query

    # Add NOT NULL conditions
    not_null_clause = ' AND '.join(not_null_conditions)

    if where_match:
        # Add to existing WHERE clause
        # Find the end of WHERE clause
        where_end = where_match.end(1)
        # Insert before GROUP BY
        insert_pos = query.upper().find('GROUP BY')

        # Add AND to connect with existing conditions
        fixed_query = (
                query[:insert_pos] +
                f' AND {not_null_clause} ' +
                query[insert_pos:]
        )
    else:
        # No WHERE clause, need to add one
        from_match = re.search(r'FROM\s+\w+\s*', query, re.IGNORECASE)
        if from_match:
            insert_pos = from_match.end()
            # Check if there's already something after FROM (like JOIN)
            next_keyword_match = re.search(r'(GROUP|ORDER|$)', query[insert_pos:], re.IGNORECASE)
            if next_keyword_match:
                insert_pos += next_keyword_match.start()

            fixed_query = (
                    query[:insert_pos] +
                    f' WHERE {not_null_clause} ' +
                    query[insert_pos:]
            )
        else:
            # Couldn't parse properly, return original
            return query

    return fixed_query


def fix_special_column_quotes(query: str) -> str:
    """
    Add quotes to special columns item_# and discount_% in PO_DETAILS table if not already quoted.
    """
    # Check if query involves PO_DETAILS table
    if not re.search(r'\bPO_DETAILS\b', query, re.IGNORECASE):
        return query

    # Pattern to find unquoted item_# and discount_%
    # Negative lookbehind to ensure not already quoted
    patterns = [
        (r'(?<!")(\bitem_#\b)(?!")', r'"\1"'),
        (r'(?<!")(\bdiscount_%\b)(?!")', r'"\1"')
    ]

    fixed_query = query
    for pattern, replacement in patterns:
        fixed_query = re.sub(pattern, replacement, fixed_query, flags=re.IGNORECASE)

    return fixed_query


def add_qualify_for_distinct_purchase_order(query: str) -> str:
    """
    Add QUALIFY ROW_NUMBER() clause when DISTINCT PURCHASE_ORDER is used
    to get only the latest entry for each PO.
    """
    # Check if query has DISTINCT and PURCHASE_ORDER
    if not (re.search(r'\bDISTINCT\b', query, re.IGNORECASE) and
            re.search(r'\bPURCHASE_ORDER\b', query, re.IGNORECASE)):
        return query

    # Check if QUALIFY already exists
    if re.search(r'\bQUALIFY\b', query, re.IGNORECASE):
        return query

    # Check if it's a SELECT DISTINCT query with PURCHASE_ORDER
    select_pattern = r'SELECT\s+DISTINCT\s+.*?\bPURCHASE_ORDER\b'
    if not re.search(select_pattern, query, re.IGNORECASE | re.DOTALL):
        return query

    # Find where to insert QUALIFY (just before the semicolon or at the end)
    # Remove trailing semicolon if exists
    query = query.rstrip()
    if query.endswith(';'):
        query = query[:-1]

    # Add QUALIFY clause
    qualify_clause = "\nQUALIFY ROW_NUMBER() OVER (PARTITION BY PURCHASE_ORDER ORDER BY PO_ENTRY_DATE DESC) = 1"

    # Add the clause and semicolon
    fixed_query = query + qualify_clause + ';'

    return fixed_query


def fix_ap_invoice_paid_vendor_columns(query: str) -> str:
    """
    Fix vendor column names in AP_INVOICE_PAID table:
    - VENDOR_NAME -> ACCOUNT_NAME
    - VENDOR_ID/VENDOR_NUM/VENDOR_NUMBER -> ACCOUNT_NUM
    """
    # Check if query involves AP_INVOICE_PAID table
    if not re.search(r'\bAP_INVOICE_PAID\b', query, re.IGNORECASE):
        return query

    # Replace VENDOR_NAME with ACCOUNT_NAME (both quoted and unquoted)
    # Pattern handles: VENDOR_NAME, "VENDOR_NAME", vendor_name, "vendor_name"
    query = re.sub(r'\b(VENDOR_NAME)\b', 'ACCOUNT_NAME', query, flags=re.IGNORECASE)
    query = re.sub(r'"(VENDOR_NAME)"', '"ACCOUNT_NAME"', query, flags=re.IGNORECASE)

    # Replace VENDOR_ID, VENDOR_NUM, VENDOR_NUMBER with ACCOUNT_NUM
    vendor_id_patterns = [
        r'\b(VENDOR_ID)\b',
        r'\b(VENDOR_NUM)\b',
        r'\b(VENDOR_NUMBER)\b'
    ]

    for pattern in vendor_id_patterns:
        query = re.sub(pattern, 'ACCOUNT_NUM', query, flags=re.IGNORECASE)
        # Also handle quoted versions
        quoted_pattern = pattern.replace(r'\b', r'"').replace(r'\b', r'"')
        query = re.sub(quoted_pattern, '"ACCOUNT_NUM"', query, flags=re.IGNORECASE)

    return query


def auto_fix_sql_query(query: str, schema_text: str) -> Tuple[str, List[str]]:
    """
    Main function to automatically fix common SQL query issues.

    Args:
        query: Original SQL query
        schema_text: Schema information in text format

    Returns:
        Tuple of (fixed_query, list_of_fixes_applied)
    """
    fixes_applied = []
    original_query = query

    # Parse schema
    schema_dict = extract_schema_info(schema_text)

    # Fix 1: COUNT -> COUNT(DISTINCT)
    query_after_count_fix = fix_count_distinct(query)
    if query_after_count_fix != query:
        fixes_applied.append("Added DISTINCT to COUNT functions")
        query = query_after_count_fix

    # Fix 2: String comparisons = -> ILIKE '%value%'
    query_after_string_fix = fix_string_comparisons(query, schema_dict)
    if query_after_string_fix != query:
        fixes_applied.append("Changed string column comparisons from = to ILIKE with wildcards")
        query = query_after_string_fix

    # Fix 3: Add IS NOT NULL for grouped columns when using LIMIT
    query_after_null_fix = fix_null_in_grouped_columns(query)
    if query_after_null_fix != query:
        fixes_applied.append("Added IS NOT NULL conditions for grouped columns to exclude NULL results")
        query = query_after_null_fix

    # Fix 4: Add quotes to special columns in PO_DETAILS
    query_after_quote_fix = fix_special_column_quotes(query)
    if query_after_quote_fix != query:
        fixes_applied.append("Added quotes to special columns (item_#, discount_%) in PO_DETAILS")
        query = query_after_quote_fix

    # Fix 5: Add QUALIFY for DISTINCT PURCHASE_ORDER queries
    query_after_qualify_fix = add_qualify_for_distinct_purchase_order(query)
    if query_after_qualify_fix != query:
        fixes_applied.append("Added QUALIFY ROW_NUMBER() to get latest entry per Purchase Order")
        query = query_after_qualify_fix

    # Fix 6: Fix vendor column names in AP_INVOICE_PAID table
    query_after_vendor_fix = fix_ap_invoice_paid_vendor_columns(query)
    if query_after_vendor_fix != query:
        fixes_applied.append(
            "Fixed vendor column names in AP_INVOICE_PAID table (VENDOR_NAME->ACCOUNT_NAME, VENDOR_ID/NUM/NUMBER->ACCOUNT_NUM)")
        query = query_after_vendor_fix

    return query, fixes_applied


# Simple function to integrate into your main.py
def fix_generated_sql(sql_query: str, schema_text: str) -> str:
    """
    Simple integration function that returns the fixed SQL query.
    Use this in your main.py after LLM generates the SQL.
    """
    fixed_query, fixes = auto_fix_sql_query(sql_query, schema_text)

    return fixed_query