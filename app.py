import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ================= CONFIG =================
st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

# ================= GOOGLE SHEETS =================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"], scopes=SCOPES
)
gc = gspread.authorize(creds)
sh = gc.open(st.secrets["SHEET_NAME"])

users_ws = sh.worksheet("users")
progress_ws = sh.worksheet("progress")
tests_ws = sh.worksheet("tests")
analytics_ws = sh.worksheet("analytics")

# ================= HELPERS =================
def hash_pw(p): 
    return hashlib.sha256(p.encode()).hexdigest()

def load_all_questions():
    qs = []
    for f in os.listdir():
        if f.endswith(".json") and f != "users.json":
            with open(f, encoding="utf-8") as file:
                data = json.load(file)
                for q in data:
                    q["options"] = [
                        q["choice_a"], q["choice_b"],
                        q["choice_c"], q["choice_d"],
                        q.get("choice_e")
                    ]
                    q["answer"] = q["correct_answer"]
                    q["question"] = q["stem"]
                    qs.append(q)
    return qs

QUESTIONS = load_all_questions()
SYSTEMS = sorted(set(q["system"] for q in QUESTIONS))

# ================= SESSION INIT =================
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "login"

# ================= AUTH =================
def login(username, pw):
    records = users_ws.get_all_records()
    for r in records:
        if r["username"] == username and r["password_hash"] == hash_pw(pw):
            return True
    return False

def signup(username, pw):
    users_ws.append_row([username, hash_pw(pw), datetime.now().isoformat()])
    progress_ws.append_row([username, "[]", "[]", "[]", "[]", "{}"])

# ================= LOGIN PAGE =================
if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")

    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            if login(u, p):
                st.session_state.user = u
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        nu = st.text_input("New username")
        np = st.text_input("New password", type="password")
        if st.button("Create Account"):
            signup(nu, np)
            st.success("Account created. Please login.")

    st.stop()

# ================= HOME =================
if st.session_state.page == "home":
    st.sidebar.title(f"👤 {st.session_state.user}")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    st.title("🏠 Home")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧪 Create a Test"):
            st.session_state.page = "create"

    with col2:
        if st.button("📚 Previous Tests"):
            st.session_state.page = "previous"

# ================= CREATE TEST =================
if st.session_state.page == "create":
    st.title("🧪 Create Test")

    num_q = st.slider("Number of questions", 1, 50, 20)
    mode = st.radio("Mode", ["Reading", "Test"])
    systems = st.multiselect("Systems", ["All"] + SYSTEMS, default="All")
    filters = st.multiselect(
        "Filters",
        ["All", "Unused", "Correct", "Incorrect", "Marked"],
        default="All"
    )

    if st.button("Start Test"):
        pool = QUESTIONS.copy()
        if "All" not in systems:
            pool = [q for q in pool if q["system"] in systems]

        selected = random.sample(pool, min(num_q, len(pool)))
        st.session_state.test = {
            "id": str(uuid.uuid4()),
            "questions": selected,
            "answers": {},
            "index": 0,
            "mode": mode,
            "start": time.time()
        }
        st.session_state.page = "test"
        st.rerun()

# ================= TEST PAGE =================
if st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]

    st.title(f"Question {test['index']+1}/{len(test['questions'])}")
    st.markdown(q["question"])

    choice = st.radio(
        "Select answer",
        q["options"],
        index=q["options"].index(test["answers"].get(q["id"])) 
        if q["id"] in test["answers"] else None,
        key=q["id"]
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Submit"):
            test["answers"][q["id"]] = choice
            if test["mode"] == "Reading":
                if choice == q["answer"]:
                    st.success("Correct")
                else:
                    st.error("Incorrect")
                st.info(q["explanation"])

    with col2:
        if st.button("Next"):
            test["index"] += 1
            if test["index"] >= len(test["questions"]):
                st.session_state.page = "review"
            st.rerun()

    if st.button("🛑 End Test"):
        st.session_state.page = "review"
        st.rerun()

# ================= REVIEW =================
if st.session_state.page == "review":
    st.title("📊 Test Review")

    correct = 0
    for q in st.session_state.test["questions"]:
        if st.session_state.test["answers"].get(q["id"]) == q["answer"]:
            correct += 1

    total = len(st.session_state.test["questions"])
    st.metric("Score", f"{correct}/{total}", f"{correct/total*100:.1f}%")

    for q in st.session_state.test["questions"]:
        st.markdown(q["question"])
        st.write("Your answer:", st.session_state.test["answers"].get(q["id"]))
        st.write("Correct answer:", q["answer"])
        st.info(q["explanation"])

    if st.button("🏠 Back Home"):
        st.session_state.page = "home"
        st.rerun()