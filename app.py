import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

# ================= CONFIG & STYLING =================

st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

# CSS to make the app feel more like a mobile app
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; margin-bottom: 10px; }
    [data-testid="stSidebar"] { min-width: 250px; }
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
        if f.endswith(".json") and f != "questions.json": # Adjust if main file is questions.json
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
    # Reduced API calls by fetching only when necessary
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
        progress_ws.update(f"B{row}:E{row}", [[
            json.dumps(list(prog["used"])),
            json.dumps(list(prog["correct"])),
            json.dumps(list(prog["incorrect"])),
            json.dumps(list(prog["marked"]))
        ]])
    except:
        progress_ws.append_row([username, json.dumps(list(prog["used"])), json.dumps(list(prog["correct"])), json.dumps(list(prog["incorrect"])), json.dumps(list(prog["marked"]))])

def save_current_answer(test, q):
    if "current_choice" in st.session_state and st.session_state.current_choice:
        for k, v in q["options_map"].items():
            if v == st.session_state.current_choice:
                test["answers"][q["id"]] = k
                break

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

def signup(username, pw):
    if any(r["username"] == username for r in users_ws.get_all_records()):
        return False
    users_ws.append_row([username, hash_pw(pw), datetime.now().isoformat()])
    progress_ws.append_row([username, "[]", "[]", "[]", "[]"])
    return True

# ================= ROUTING =================

# Force login if user lost in session state
if st.session_state.user is None:
    st.session_state.page = "login"

# ================= LOGIN PAGE =================

if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")
    t1, t2 = st.tabs(["Login", "Sign Up"])
    with t1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            if login(u, p):
                st.session_state.user = u
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error("Invalid credentials")
    with t2:
        nu = st.text_input("New username")
        np = st.text_input("New password", type="password")
        if st.button("Create Account"):
            if signup(nu, np):
                st.success("Account created. Please login.")
            else:
                st.error("Username already exists")

# ================= HOME PAGE =================

elif st.session_state.page == "home":
    st.title(f"🏠 Welcome, {st.session_state.user}")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧪 Create New Test"):
            st.session_state.page = "create"
            st.rerun()
    with col2:
        if st.button("📚 Previous Tests & Analytics"):
            st.session_state.page = "previous_menu"
            st.rerun()
            
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

# ================= CREATE TEST =================

elif st.session_state.page == "create":
    st.title("🧪 Create Test")
    prog = get_user_progress(st.session_state.user)
    
    num_q = st.slider("Number of questions", 1, 50, 20)
    mode = st.radio("Mode", ["Reading", "Test"])
    systems = st.multiselect("Systems", ["All"] + SYSTEMS, default="All")
    filters = st.multiselect("Filters", ["All", "Unused", "Correct", "Incorrect", "Marked"], default="All")
    
    pool = QUESTIONS.copy()
    if "All" not in systems:
        pool = [q for q in pool if q["system"] in systems]
    if "All" not in filters:
        if "Unused" in filters: pool = [q for q in pool if q["id"] not in prog["used"]]
        if "Correct" in filters: pool = [q for q in pool if q["id"] in prog["correct"]]
        if "Incorrect" in filters: pool = [q for q in pool if q["id"] in prog["incorrect"]]
        if "Marked" in filters: pool = [q for q in pool if q["id"] in prog["marked"]]
        
    st.info(f"Available questions: {len(pool)}")
    
    if st.button("Start Test"):
        if not pool:
            st.error("No questions match your filters.")
        else:
            selected = random.sample(pool, min(num_q, len(pool)))
            st.session_state.test = {
                "id": str(uuid.uuid4()),
                "questions": selected,
                "answers": {},
                "marked": set(),
                "index": 0,
                "mode": mode,
                "start": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "systems": ", ".join(systems)
            }
            st.session_state.page = "test"
            st.rerun()
            
    if st.button("Back"):
        st.session_state.page = "home"
        st.rerun()

# ================= TEST INTERFACE =================

elif st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]
    
    st.subheader(f"Question {test['index'] + 1} of {len(test['questions'])}")
    
    # Progress bar
    st.progress((test["index"] + 1) / len(test['questions']))
    
    st.markdown(f"**{q['question']}**")
    
    # Answer selection
    current_ans_id = test["answers"].get(q["id"])
    default_idx = None
    if current_ans_id:
        default_idx = list(q["options_map"].keys()).index(current_ans_id)

    choice_letter = st.radio(
        "Select your answer:",
        options=list(q["options_map"].keys()),
        format_func=lambda x: f"{x}: {q['options_map'][x]}",
        index=default_idx,
        key=f"radio_{q['id']}_{test['index']}"
    )
    
    if choice_letter:
        test["answers"][q["id"]] = choice_letter

    # Reading Mode Logic
    if test["mode"] == "Reading" and choice_letter:
        if choice_letter == q["answer"]:
            st.success(f"Correct! Answer: {q['answer']}")
        else:
            st.error(f"Incorrect. Your choice: {choice_letter}. Correct: {q['answer']}")
        st.info(f"**Explanation:** {q.get('explanation', 'No explanation available.')}")

    st.divider()
    
    # Navigation
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("⬅ Previous") and test["index"] > 0:
            test["index"] -= 1
            st.rerun()
    with c2:
        if test["index"] < len(test["questions"]) - 1:
            if st.button("Next ➡"):
                test["index"] += 1
                st.rerun()
        else:
            if st.button("Finish 🏁"):
                st.session_state.page = "review_score"
                st.rerun()
    with c3:
        label = "🚩 Unmark" if q["id"] in test["marked"] else "🚩 Mark"
        if st.button(label):
            if q["id"] in test["marked"]: test["marked"].remove(q["id"])
            else: test["marked"].add(q["id"])
            st.rerun()
    with c4:
        if st.button("🏠 End & Save"):
            st.session_state.page = "review_score"
            st.rerun()

# ================= REVIEW/SCORE PAGE =================

elif st.session_state.page == "review_score":
    st.title("📊 Test Results")
    test = st.session_state.test
    prog = get_user_progress(st.session_state.user)
    
    correct_count = 0
    results_data = []
    
    for q in test["questions"]:
        qid = q["id"]
        u_ans = test["answers"].get(qid)
        is_correct = u_ans == q["answer"]
        
        if is_correct: correct_count += 1
        
        # Update progress sets
        prog["used"].add(qid)
        if is_correct: prog["correct"].add(qid)
        else: prog["incorrect"].add(qid)
        
    prog["marked"].update(test["marked"])
    save_user_progress(st.session_state.user, prog)
    
    # Log to Google Sheets
    tests_ws.append_row([
        st.session_state.user, test["id"], test["start"], test["mode"], 
        len(test["questions"]), correct_count, test["systems"], json.dumps(test["answers"]), json.dumps([q['id'] for q in test["questions"]])
    ])
    
    st.metric("Final Score", f"{correct_count}/{len(test['questions'])}", f"{(correct_count/len(test['questions']))*100:.1f}%")
    
    if st.button("View Detailed Review"):
        st.session_state.page = "detailed_review"
        st.rerun()
    
    if st.button("Return Home"):
        st.session_state.page = "home"
        st.rerun()

# ================= DETAILED REVIEW =================

elif st.session_state.page == "detailed_review":
    st.title("📝 Detailed Review")
    test = st.session_state.test
    
    for i, q in enumerate(test["questions"]):
        u_ans = test["answers"].get(q["id"], "No Answer")
        is_correct = u_ans == q["answer"]
        
        with st.expander(f"Q{i+1}: {'✅' if is_correct else '❌'} {q['question'][:50]}..."):
            st.write(q["question"])
            for char, text in q["options_map"].items():
                if text:
                    color = "green" if char == q["answer"] else ("red" if char == u_ans else "black")
                    st.markdown(f"<p style='color:{color}'>{char}: {text}</p>", unsafe_allow_html=True)
            st.info(f"**Explanation:** {q.get('explanation', 'None')}")

    if st.button("Back to Home"):
        st.session_state.page = "home"
        st.rerun()

# ================= PREVIOUS TESTS MENU =================

elif st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests & Records")
    
    choice = st.radio("Select an option:", ["Last Test", "Previous Tests List", "Analytics"])
    
    all_tests = [r for r in tests_ws.get_all_records() if r.get("username") == st.session_state.user]
    
    if choice == "Last Test":
        if st.session_state.test:
            st.write(f"Resuming your {st.session_state.test['mode']} test from {st.session_state.test['start']}")
            if st.button("Continue where I left off"):
                st.session_state.page = "test"
                st.rerun()
        else:
            st.warning("No active session found. Start a new test!")

    elif choice == "Previous Tests List":
        if not all_tests:
            st.info("No previous tests found.")
        else:
            for t in reversed(all_tests):
                with st.expander(f"📅 {t['start']} - {t['mode']} ({t['score']}/{t['total_questions']})"):
                    st.write(f"**System:** {t.get('systems', 'All')}")
                    st.write(f"**Score:** {t['score']} / {t['total_questions']}")
                    # Button to review could be added here by reconstructing the test object

    elif choice == "Analytics":
        prog = get_user_progress(st.session_state.user)
        total_q = len(QUESTIONS)
        used = len(prog["used"])
        unused = total_q - used
        correct = len(prog["correct"])
        incorrect = len(prog["incorrect"])
        
        st.subheader("Question Bank Usage")
        fig1 = px.pie(names=["Used", "Unused"], values=[used, unused], color_discrete_sequence=['#3498db', '#ecf0f1'])
        st.plotly_chart(fig1)
        
        st.subheader("Performance Accuracy")
        fig2 = px.pie(names=["Correct", "Incorrect"], values=[correct, incorrect], color_discrete_sequence=['#2ecc71', '#e74c3c'])
        st.plotly_chart(fig2)

    if st.button("Back to Home"):
        st.session_state.page = "home"
        st.rerun()
