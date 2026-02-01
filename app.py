import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

# ================= CONFIG & STYLING =================

st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# ================= GOOGLE SHEETS =================

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheets():
    gc = get_gspread_client()
    sh = gc.open(st.secrets["SHEET_NAME"])
    return sh.worksheet("users"), sh.worksheet("progress"), sh.worksheet("tests")

users_ws, progress_ws, tests_ws = get_sheets()

# ================= HELPERS =================

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

@st.cache_data
def load_all_questions():
    qs = []
    for f in os.listdir():
        if f.endswith(".json"):
            with open(f, encoding="utf-8") as file:
                data = json.load(file)
                for q in data:
                    q_id = f"{q.get('system', 'gen')}_{q.get('id', uuid.uuid4())}"
                    q["id"] = q_id
                    q["options_map"] = {
                        "A": q["choice_a"], "B": q["choice_b"], "C": q["choice_c"], 
                        "D": q["choice_d"], "E": q.get("choice_e")
                    }
                    q["options"] = [v for v in q["options_map"].values() if v]
                    q["answer"] = q["correct_answer"]
                    q["question"] = q["stem"]
                    qs.append(q)
    return qs

QUESTIONS = load_all_questions()
SYSTEMS = sorted(set(q["system"] for q in QUESTIONS))

def get_user_progress(username):
    rows = progress_ws.get_all_records()
    for r in rows:
        if r.get("username") == username:
            return {
                "used": set(json.loads(r.get("used", "[]") or "[]")),
                "correct": set(json.loads(r.get("correct", "[]") or "[]")),
                "incorrect": set(json.loads(r.get("incorrect", "[]") or "[]")),
                "marked": set(json.loads(r.get("marked", "[]") or "[]")),
            }
    return {"used": set(), "correct": set(), "incorrect": set(), "marked": set()}

def save_user_progress(username, prog):
    try:
        cell = progress_ws.find(username)
        row = cell.row
        # Fixed DeprecationWarning: values first, then range
        progress_ws.update(values=[[
            json.dumps(list(prog["used"])),
            json.dumps(list(prog["correct"])),
            json.dumps(list(prog["incorrect"])),
            json.dumps(list(prog["marked"]))
        ]], range_name=f"B{row}:E{row}")
    except:
        progress_ws.append_row([username, "[]", "[]", "[]", "[]"])

# ================= SESSION INIT =================

if "page" not in st.session_state:
    st.session_state.page = "login"
if "user" not in st.session_state:
    st.session_state.user = None
if "test" not in st.session_state:
    st.session_state.test = None

# ================= AUTH =================

def login(username, pw):
    for r in users_ws.get_all_records():
        if r["username"] == username and r["password_hash"] == hash_pw(pw):
            return True
    return False

# ================= PAGES =================

if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        if login(u, p):
            st.session_state.user = u
            st.session_state.page = "home"
            st.rerun()
        else:
            st.error("Invalid credentials")

elif st.session_state.page == "home":
    st.title(f"🏠 Home - {st.session_state.user}")
    if st.button("🧪 Create Test"):
        st.session_state.page = "create"
        st.rerun()
    if st.button("📚 Previous Tests"):
        st.session_state.page = "previous_menu"
        st.rerun()
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

elif st.session_state.page == "create":
    st.title("🧪 Create Test")
    prog = get_user_progress(st.session_state.user)
    num_q = st.slider("Questions", 1, 40, 20)
    mode = st.radio("Mode", ["Reading", "Test"])
    systems = st.multiselect("Systems", SYSTEMS, default=SYSTEMS)
    
    if st.button("Start"):
        pool = [q for q in QUESTIONS if q["system"] in systems]
        selected = random.sample(pool, min(num_q, len(pool)))
        st.session_state.test = {
            "id": str(uuid.uuid4()),
            "questions": selected,
            "answers": {},
            "index": 0,
            "mode": mode,
            "start": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "marked": []
        }
        st.session_state.page = "test"
        st.rerun()

elif st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]
    st.subheader(f"Question {test['index'] + 1} / {len(test['questions'])}")
    st.write(q["question"])
    
    ans = st.radio("Select Option", list(q["options_map"].keys()), 
                   format_func=lambda x: f"{x}: {q['options_map'][x]}",
                   key=f"q_{test['index']}", index=None)
    
    if ans:
        test["answers"][q["id"]] = ans
        if test["mode"] == "Reading":
            if ans == q["answer"]: st.success("Correct!")
            else: st.error(f"Incorrect. Correct: {q['answer']}")
            st.info(q.get("explanation", "No explanation"))

    col1, col2, col3 = st.columns(3)
    if col1.button("Prev") and test["index"] > 0:
        test["index"] -= 1
        st.rerun()
    if col2.button("Next") and test["index"] < len(test["questions"]) - 1:
        test["index"] += 1
        st.rerun()
    if col3.button("End & Save"):
        # Save to sheets
        correct = sum(1 for q in test["questions"] if test["answers"].get(q["id"]) == q["answer"])
        tests_ws.append_row([
            st.session_state.user, test["id"], test["start"], test["mode"], 
            len(test["questions"]), correct, json.dumps(test["answers"]), test["index"]
        ])
        st.session_state.page = "home"
        st.rerun()

elif st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests")
    tab1, tab2, tab3 = st.tabs(["Last Test", "History", "Analytics"])
    
    # Safely fetch records to prevent KeyError
    all_recs = tests_ws.get_all_records()
    user_recs = [r for r in all_recs if r.get("username") == st.session_state.user]
    
    with tab1:
        if user_recs:
            last = user_recs[-1]
            st.write(f"Last test on {last['start']} stopped at Q{int(last['index'])+1}")
            if st.button("Resume Last Test"):
                # Logic to reconstruct test object would go here
                st.info("Resuming feature requires session serialization.")
        else:
            st.info("No previous tests.")

    with tab2:
        if user_recs:
            df = pd.DataFrame(user_recs)[["start", "mode", "total_questions", "score"]]
            st.dataframe(df)
        else:
            st.info("No history found.")

    with tab3:
        if user_recs:
            total_correct = sum(r['score'] for r in user_recs)
            total_qs = sum(r['total_questions'] for r in user_recs)
            fig = px.pie(names=["Correct", "Incorrect"], values=[total_correct, total_qs - total_correct])
            st.plotly_chart(fig)

    if st.button("Back"):
        st.session_state.page = "home"
        st.rerun()
