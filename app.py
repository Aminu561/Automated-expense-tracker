import streamlit as st
import os
import sqlite3
import pytesseract
from PIL import Image
import pandas as pd
import re
from datetime import datetime
import numpy as np
from typing import Dict, List, Any, Optional

# PDF to image conversion
from pdf2image import convert_from_path

# --- Google Sheets API ---
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ---------- CONFIG ----------
SCOPES: List[str] = ['https://www.googleapis.com/auth/spreadsheets']
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
DB_PATH = 'expenses.db'
TEMP_DIR = "temp_uploads"

# Predefined categories
EXPENSE_CATEGORIES: Dict[str, List[str]] = {
    'food': ['restaurant', 'cafe', 'pizza', 'burger', 'coffee', 'grocery', 'supermarket', 'fresh foods'],
    'transportation': ['uber', 'lyft', 'taxi', 'gas', 'fuel', 'parking', 'metro'],
    'shopping': ['amazon', 'walmart', 'target', 'mall', 'store', 'shop'],
    'utilities': ['electric', 'water', 'internet', 'phone', 'cable'],
    'entertainment': ['movie', 'theater', 'netflix', 'spotify', 'game'],
    'healthcare': ['pharmacy', 'doctor', 'hospital', 'clinic', 'medical'],
    'other': []
}

# ---------- DATABASE ----------
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT,
                  amount REAL,
                  vendor TEXT,
                  category TEXT,
                  raw_text TEXT,
                  filename TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# ---------- GOOGLE SHEETS ----------
def get_google_sheets_service():
    creds: Optional[Credentials] = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)

def export_to_google_sheets(expense_data: Dict[str, Any], spreadsheet_id: str) -> bool:
    try:
        service = get_google_sheets_service()
        range_name = 'Sheet1'
        values = [[
            expense_data['date'], 
            expense_data['amount'], 
            expense_data['vendor'], 
            expense_data['category']
        ]]
        body = {'values': values}
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, 
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return True
    except Exception as e:
        st.error(f"Error exporting to Google Sheets: {e}")
        return False

# ---------- OCR ----------
def configure_tesseract():
    try:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        st.error("Tesseract OCR not found. Please install it and set the correct path.")
        st.stop()

def extract_text_from_image(image_path: str) -> str:
    try:
        image = Image.open(image_path)
        return pytesseract.image_to_string(image)
    except Exception as e:
        st.error(f"Error extracting text: {e}")
        return ""

def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        images = convert_from_path(pdf_path)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
        return text
    except Exception as e:
        st.error(f"Error processing PDF: {e}")
        return ""

# ---------- PARSING ----------
def parse_expense_data(text: str) -> Dict[str, Any]:
    amounts = [float(s) for s in re.findall(r'(\d+\.\d{2})', text.replace(',', '.'))]
    total_amount = np.max(amounts) if amounts else 0.0

    date_patterns = [
        r'\d{4}-\d{2}-\d{2}',
        r'\d{1,2}/\d{1,2}/\d{2,4}',
        r'\d{1,2}-\d{1,2}-\d{2,4}',
        r'[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}'
    ]
    date_found = None
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_found = match.group(0)
            break

    date_parsed = datetime.now().strftime('%Y-%m-%d')
    if date_found:
        try:
            date_parsed = pd.to_datetime(date_found, errors='coerce').strftime('%Y-%m-%d')
        except:
            pass

    lines = text.strip().split('\n')
    vendor = 'Unknown'
    for line in lines:
        line = line.strip()
        if not re.match(r'^((\$?\d+\.?\d*)|(\d{1,2}[/-]\d{1,2}))', line):
            if len(line) > 3 and 'receipt' not in line.lower() and 'tax' not in line.lower():
                parts = line.split()
                if parts:
                    vendor = parts[0]
                    break
.....
    return {
        'amount': total_amount,
        'date': date_parsed,
        'vendor': vendor,
        'description': text.strip()[:200]
    }

def categorize_expense(vendor: str, description: str) -> str:
    text = (vendor + ' ' + description).lower()
    for category, keywords in EXPENSE_CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return 'other'

# ---------- STREAMLIT APP ----------
st.set_page_config(page_title="Automated Expense Tracker", layout="wide")
init_db()
configure_tesseract()

st.title("Automated Expense Tracker 🧾")

# --- Upload Section ---
with st.expander("Upload a New Receipt"):
    uploaded_file = st.file_uploader("Choose a file", type=['png', 'jpg', 'jpeg', 'gif', 'pdf'])
    
    if uploaded_file is not None:
        os.makedirs(TEMP_DIR, exist_ok=True)
        filepath = os.path.join(TEMP_DIR, uploaded_file.name)
        with open(filepath, "wb") as f:
            f.write(uploaded_file.getbuffer())

        try:
            with st.spinner("Processing receipt..."):
                if uploaded_file.name.lower().endswith(".pdf"):
                    raw_text = extract_text_from_pdf(filepath)
                else:
                    raw_text = extract_text_from_image(filepath)

                if not raw_text.strip():
                    st.warning("No text detected. Try a clearer image or PDF.")
                else:
                    expense_data = parse_expense_data(raw_text)
                    category = categorize_expense(expense_data['vendor'], expense_data['description'])

                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute('''INSERT INTO expenses (date, amount, vendor, category, raw_text, filename)
                                 VALUES (?, ?, ?, ?, ?, ?)''',
                              (expense_data['date'], expense_data['amount'], expense_data['vendor'],
                               category, raw_text, uploaded_file.name))
                    conn.commit()
                    conn.close()

                    st.success('Receipt processed and stored successfully!')
                    st.write({
                        'Vendor': expense_data['vendor'],
                        'Date': expense_data['date'],
                        'Amount': f"${expense_data['amount']:.2f}",
                        'Category': category
                    })

                    if st.button("Export Latest Expense to Google Sheets"):
                        spreadsheet_id = "YOUR_SPREADSHEET_ID_HERE"
                        if export_to_google_sheets(expense_data | {'category': category}, spreadsheet_id):
                            st.success("Expense exported to Google Sheets!")
                        else:
                            st.error("Failed to export to Google Sheets.")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

# --- Dashboard ---
st.header("Dashboard")

conn = sqlite3.connect(DB_PATH)
recent_expenses_df = pd.read_sql_query("SELECT * FROM expenses ORDER BY created_at DESC LIMIT 10", conn)
conn.close()

if recent_expenses_df.empty:
    st.info("No expenses recorded yet.")
else:
    st.subheader("Recent Expenses")
    st.dataframe(recent_expenses_df, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        conn = sqlite3.connect(DB_PATH)
        category_summary_df = pd.read_sql_query("SELECT category, SUM(amount) as total FROM expenses GROUP BY category", conn)
        conn.close()
        if not category_summary_df.empty:
            st.subheader("Spending by Category")
            st.bar_chart(category_summary_df.set_index('category'))
        else:
            st.info("No data for category chart.")

    with col2:
        conn = sqlite3.connect(DB_PATH)
        monthly_spending_df = pd.read_sql_query("""
            SELECT strftime('%Y-%m', date) as month, SUM(amount) as total 
            FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12
        """, conn)
        conn.close()
        if not monthly_spending_df.empty:
            st.subheader("Monthly Spending")
            st.line_chart(monthly_spending_df.set_index('month'))
        else:
            st.info("No data for monthly chart.")

# --- All Expenses with Filters ---
st.header("All Expenses")
with st.expander("Filter Expenses"):
    conn = sqlite3.connect(DB_PATH)
    all_expenses_df = pd.read_sql_query("SELECT * FROM expenses", conn)
    conn.close()

    if all_expenses_df.empty:
        st.info("No expenses recorded yet.")
    else:
        categories = ['all'] + sorted(all_expenses_df['category'].dropna().unique())
        selected_category = st.selectbox('Category', categories, index=0)

        date_range = st.date_input("Select Date Range")
        if isinstance(date_range, tuple) and len(date_range) == 2:
            date_from, date_to = date_range
        else:
            date_from, date_to = None, None

        if st.button("Apply Filters"):
            query = "SELECT * FROM expenses WHERE 1=1"
            params: List[Any] = []
            
            if selected_category != 'all':
                query += " AND category = ?"
                params.append(selected_category)
            
            if date_from:
                query += " AND date >= ?"
                params.append(date_from.strftime('%Y-%m-%d'))
            
            if date_to:
                query += " AND date <= ?"
                params.append(date_to.strftime('%Y-%m-%d'))
            
            query += " ORDER BY date DESC"
            
            conn = sqlite3.connect(DB_PATH)
            filtered_df = pd.read_sql_query(query, conn, params=params)
            conn.close()

            if filtered_df.empty:
                st.warning("No expenses match your filters.")
            else:
                st.dataframe(filtered_df, use_container_width=True)