import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

# ================= CONFIG =================
st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

# ================= GOOGLE SHEETS (CACHED) =================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_sheets():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open(st.secrets["SHEET_NAME"])
    return (
        sh.worksheet("users"),
        sh.worksheet("progress"),
        sh.worksheet("tests")
    )

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
                    q["id"] = f"{q['system']}_{q['id']}"
                    q["options_map"] = {
                        "A": q["choice_a"],
                        "B": q["choice_b"],
                        "C": q["choice_c"],
                        "D": q["choice_d"],
                        "E": q.get("choice_e")
                    }
                    q["question"] = q["stem"]
                    q["answer"] = q["correct_answer"]
                    qs.append(q)
    return qs

QUESTIONS = load_all_questions()
SYSTEMS = sorted(set(q["system"] for q in QUESTIONS))

def get_user_progress(username):
    rows = progress_ws.get_all_records()
    for r in rows:
        if r["username"] == username:
            return {k: set(json.loads(r[k])) for k in ["used","correct","incorrect","marked"]}
    progress_ws.append_row([username,"[]","[]","[]","[]"])
    return {"used":set(),"correct":set(),"incorrect":set(),"marked":set()}

def save_user_progress(username, prog):
    cell = progress_ws.find(username)
    progress_ws.update(
        f"B{cell.row}:E{cell.row}",
        [[json.dumps(list(prog[k])) for k in prog]]
    )

# ================= SESSION INIT =================
if "page" not in st.session_state:
    st.session_state.page = "login"

# ================= AUTH =================
def login(u, p):
    return any(
        r["username"] == u and r["password_hash"] == hash_pw(p)
        for r in users_ws.get_all_records()
    )

def signup(u, p):
    if any(r["username"] == u for r in users_ws.get_all_records()):
        return False
    users_ws.append_row([u, hash_pw(p), datetime.now().isoformat()])
    progress_ws.append_row([u,"[]","[]","[]","[]"])
    return True

# ================= LOGIN =================
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
                st.success("Account created")
            else:
                st.error("Username exists")
    st.stop()

# ================= HOME =================
if st.session_state.page == "home":
    st.sidebar.title(st.session_state.user)
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    st.title("🏠 Home")
    if st.button("🧪 Create Test"):
        st.session_state.page = "create"
        st.rerun()
    if st.button("📚 Previous Tests"):
        st.session_state.page = "previous"
        st.rerun()

# ================= CREATE TEST =================
if st.session_state.page == "create":
    prog = get_user_progress(st.session_state.user)
    st.title("🧪 Create Test")

    n = st.slider("Questions",1,50,20)
    mode = st.radio("Mode",["Reading","Test"])
    systems = st.multiselect("Systems",["All"]+SYSTEMS,default="All")

    pool = QUESTIONS
    if "All" not in systems:
        pool = [q for q in pool if q["system"] in systems]

    if st.button("Start Test"):
        st.session_state.test = {
            "id": str(uuid.uuid4()),
            "questions": random.sample(pool, min(n,len(pool))),
            "answers": {},
            "marked": set(),
            "index": 0,
            "mode": mode,
            "active": True
        }
        st.session_state.page = "test"
        st.rerun()

# ================= TEST =================
if st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]

    st.title(f"Q {test['index']+1}/{len(test['questions'])}")
    st.markdown(q["question"])

    opts = list(q["options_map"].values())
    choice = st.radio("Answer", opts, index=None if q["id"] not in test["answers"]
                      else opts.index(q["options_map"][test["answers"][q["id"]]]))

    if choice:
        for k,v in q["options_map"].items():
            if v == choice:
                test["answers"][q["id"]] = k

    c1,c2,c3,c4 = st.columns(4)
    if c1.button("⬅ Previous") and test["index"]>0:
        test["index"] -= 1; st.rerun()
    if c2.button("Next ➡"):
        if test["index"] < len(test["questions"])-1:
            test["index"] += 1
        else:
            st.session_state.page = "review"
        st.rerun()
    if c3.button("🚩 Mark"):
        test["marked"].add(q["id"])
    if c4.button("⛔ End & Save"):
        st.session_state.page = "review"
        st.rerun()

# ================= REVIEW =================
if st.session_state.page == "review":
    test = st.session_state.test
    prog = get_user_progress(st.session_state.user)

    correct = 0
    for q in test["questions"]:
        prog["used"].add(q["id"])
        if test["answers"].get(q["id"]) == q["answer"]:
            correct += 1; prog["correct"].add(q["id"])
        else:
            prog["incorrect"].add(q["id"])

    prog["marked"].update(test["marked"])
    save_user_progress(st.session_state.user, prog)

    tests_ws.append_row([
        st.session_state.user,
        test["id"],
        datetime.now().isoformat(),
        test["mode"],
        len(test["questions"]),
        correct
    ])

    st.metric("Score",f"{correct}/{len(test['questions'])}")

    for q in test["questions"]:
        st.divider()
        st.markdown(q["question"])
        st.write("Your answer:", test["answers"].get(q["id"]))
        st.write("Correct:", q["answer"])
        st.info(q.get("explanation",""))

    if st.button("🏠 Home"):
        st.session_state.page="home"; st.rerun()

# ================= PREVIOUS =================
if st.session_state.page == "previous":
    st.title("📚 Previous Tests")
    tabs = st.tabs(["Last Test","All Tests","Analytics"])

    with tabs[0]:
        if "test" in st.session_state:
            if st.button("Resume Last Test"):
                st.session_state.page="test"; st.rerun()
        else:
            st.info("No active test")

    with tabs[1]:
        rows = [r for r in tests_ws.get_all_records() if r["username"]==st.session_state.user]
        st.dataframe(pd.DataFrame(rows))

    with tabs[2]:
        prog = get_user_progress(st.session_state.user)
        fig = px.pie(
            names=["Correct","Incorrect","Unused"],
            values=[
                len(prog["correct"]),
                len(prog["incorrect"]),
                len(QUESTIONS)-len(prog["used"])
            ]
        )
        st.plotly_chart(fig)

    if st.button("🏠 Home"):
        st.session_state.page="home"; st.rerun()