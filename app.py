import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

================= CONFIG =================

st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

================= GOOGLE SHEETS =================

SCOPES = [
"https://www.googleapis.com/auth/spreadsheets",
"https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_gc():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return gspread.authorize(creds)

gc = get_gc()

@st.cache_resource
def get_sh():
    return gc.open(st.secrets["SHEET_NAME"])

sh = get_sh()

@st.cache_resource
def get_ws(name):
    return sh.worksheet(name)

users_ws = get_ws("users")
progress_ws = get_ws("progress")
tests_ws = get_ws("tests")
ongoing_tests = get_ws("ongoing_tests")

================= HELPERS =================

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
                # 🔐 Ensure GLOBAL unique ID  
                q["id"] = f"{q['system']}_{q['id']}"  

                q["options_map"] = {  
                    "A": q["choice_a"],  
                    "B": q["choice_b"],  
                    "C": q["choice_c"],  
                    "D": q["choice_d"],  
                    "E": q.get("choice_e")  
                }  

                q["options"] = [v for v in q["options_map"].values() if v]  
                q["answer"] = q["correct_answer"]  
                q["question"] = q["stem"]  

                qs.append(q)  
    return qs

QUESTIONS = load_all_questions()
ID_TO_Q = {q["id"]: q for q in QUESTIONS}
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
    progress_ws.append_row([username, "[]", "[]", "[]", "[]"])  
    return {"used": set(), "correct": set(), "incorrect": set(), "marked": set()}

def save_user_progress(username, prog):
    cell = progress_ws.find(username)
    row = cell.row
    progress_ws.update(  
        f"B{row}:E{row}",  
        [[  
            json.dumps(list(prog["used"])),  
            json.dumps(list(prog["correct"])),  
            json.dumps(list(prog["incorrect"])),  
            json.dumps(list(prog["marked"]))  
        ]]  
    )

def save_current_answer(test, q):
    if "current_choice" in st.session_state and st.session_state.current_choice:
        for k, v in q["options_map"].items():
            if v == st.session_state.current_choice:
                test["answers"][q["id"]] = k
                break

def save_ongoing(test, username):
    cell = ongoing_tests.find(username)
    created = test.get("created", datetime.now().isoformat())
    last_updated = datetime.now().isoformat()
    values = [
        test["id"],
        created,
        test["mode"],
        json.dumps(test["systems"]),
        json.dumps([q["id"] for q in test["questions"]]),
        json.dumps(test["answers"]),
        json.dumps(list(test["marked"])),
        test["index"],
        last_updated
    ]
    if cell:
        row = cell.row
        ongoing_tests.update(f"B{row}:J{row}", [values])
    else:
        ongoing_tests.append_row([username] + values)

def load_ongoing(username):
    rows = ongoing_tests.get_all_records()
    ongoing = next((r for r in rows if r.get("username") == username), None)
    if not ongoing:
        return None
    q_ids = json.loads(ongoing.get("q_ids_json", "[]"))
    questions = [ID_TO_Q.get(qid) for qid in q_ids if qid in ID_TO_Q]
    return {
        "id": ongoing["test_id"],
        "questions": questions,
        "answers": json.loads(ongoing.get("answers_json", "{}")),
        "marked": set(json.loads(ongoing.get("marked_json", "[]"))),
        "index": ongoing.get("index", 0),
        "mode": ongoing["mode"],
        "systems": json.loads(ongoing.get("systems_json", "[]")),
        "created": ongoing["created"]
    }

def delete_ongoing(username):
    cell = ongoing_tests.find(username)
    if cell:
        ongoing_tests.delete_rows(cell.row)

def start_test(pool, num_q, mode, systems):
    selected = random.sample(pool, min(num_q, len(pool)))
    st.session_state.test = {
        "id": str(uuid.uuid4()),
        "questions": selected,
        "answers": {},
        "marked": set(),
        "index": 0,
        "mode": mode,
        "created": datetime.now().isoformat(),
        "systems": ["All"] if "All" in systems else systems
    }
    st.session_state.page = "test"
    st.rerun()

================= SESSION INIT =================

if "page" not in st.session_state:
    st.session_state.page = "login"

================= AUTH =================

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

================= LOGIN =================

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
    st.stop()

================= HOME =================

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
        st.session_state.page = "previous_menu"  
        st.rerun()

================= CREATE TEST =================

if st.session_state.page == "create":
    st.title("🧪 Create Test")
    prog = get_user_progress(st.session_state.user)  
    num_q = st.slider("Number of questions", 1, 50, 20)  
    mode = st.radio("Mode", ["Reading", "Test"])  
    systems = st.multiselect("Systems", ["All"] + SYSTEMS, default="All")  
    filters = st.multiselect(  
        "Filters",  
        ["All", "Unused", "Correct", "Incorrect", "Marked"],  
        default="All"  
    )  
    pool = QUESTIONS.copy()  
    if "All" not in systems:  
        pool = [q for q in pool if q["system"] in systems]  
    if "All" not in filters:  
        if "Unused" in filters:  
            pool = [q for q in pool if q["id"] not in prog["used"]]  
        if "Correct" in filters:  
            pool = [q for q in pool if q["id"] in prog["correct"]]  
        if "Incorrect" in filters:  
            pool = [q for q in pool if q["id"] in prog["incorrect"]]  
        if "Marked" in filters:  
            pool = [q for q in pool if q["id"] in prog["marked"]]  
    st.info(f"Available questions: {len(pool)}")  
    has_ongoing = any(r.get("username") == st.session_state.user for r in ongoing_tests.get_all_records())
    if has_ongoing:
        st.warning("You have an unfinished test.")
        col_resume, col_discard = st.columns(2)
        if col_resume.button("Resume last test"):
            test_data = load_ongoing(st.session_state.user)
            if test_data:
                st.session_state.test = test_data
                st.session_state.page = "test"
                st.rerun()
        if col_discard.button("Discard and start new"):
            delete_ongoing(st.session_state.user)
            start_test(pool, num_q, mode, systems)
    else:
        if st.button("Start Test"):
            start_test(pool, num_q, mode, systems)

================= TEST =================

if st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]
    st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")  
    st.markdown(q["question"])  
    if test["mode"] == "review":
        user_letter = test["answers"].get(q["id"], None)
        correct = q["answer"]
        if user_letter:
            if user_letter == correct:
                st.success(f"Correct! ({correct})")
            else:
                st.error(f"Incorrect. You chose {user_letter}, correct is {correct}")
        else:
            st.warning(f"Not answered. Correct is {correct}")
        for letter, opt in q["options_map"].items():
            if not opt: continue
            prefix = ""
            if letter == correct:
                prefix += "✅ "
            if letter == user_letter:
                prefix += "👉 "
            st.markdown(f"{prefix}{letter}) {opt}")
        st.info(q.get("explanation", "No explanation provided."))
    else:
        radio_key = f"q_{q['id']}_answer"  
        choice = st.radio(  
            "Select answer",  
            list(q["options_map"].values()),  
            index=None if q["id"] not in test["answers"]  
            else list(q["options_map"].values()).index(  
                q["options_map"][test["answers"][q["id"]]]  
            ),  
            key=radio_key  
        )  
        st.session_state.current_choice = choice
    col1, col2, col3, col4 = st.columns(4)  
    if col1.button("⬅ Previous") and test["index"] > 0:  
        if test["mode"] != "review":
            save_current_answer(test, q)  
        test["index"] -= 1  
        st.rerun()  
    if col2.button("Next ➡"):  
        if test["mode"] != "review":
            save_current_answer(test, q)  
        if test["index"] < len(test["questions"]) - 1:  
            test["index"] += 1  
            st.rerun()  
        else:  
            if test["mode"] == "review":
                st.session_state.page = "home"
            else:
                st.session_state.page = "review"  
            st.rerun()  
    if test["mode"] != "review":
        if col3.button("🚩 Mark"):  
            if q["id"] in test["marked"]:
                test["marked"].remove(q["id"])
            else:
                test["marked"].add(q["id"])  
            st.rerun()  
        if col4.button("End session and save"):
            save_current_answer(test, q)
            save_ongoing(test, st.session_state.user)
            st.session_state.page = "home"
            st.rerun()
    # ================= READING MODE ANSWER FIX =================  
    if test["mode"] == "Reading":  
        # Show answer + explanation only after user selects an option  
        user_choice = st.session_state.current_choice  
        if user_choice:  
            correct = q["answer"]  
            explanation = q.get("explanation", "No explanation provided.")  
            # Map user choice back to letter  
            user_letter = None  
            for k, v in q["options_map"].items():  
                if v == user_choice:  
                    user_letter = k  
                    break  
            if user_letter == correct:  
                st.success(f"Correct! ({correct})")  
            else:  
                st.error(f"Incorrect. You chose {user_letter}, correct is {correct}")  
            st.info(explanation)

================= REVIEW =================

if st.session_state.page == "review":
    st.title("📊 Review")
    prog = get_user_progress(st.session_state.user)  
    correct = 0  
    for q in st.session_state.test["questions"]:  
        qid = q["id"]  
        prog["used"].add(qid)  
        if st.session_state.test["answers"].get(qid) == q["answer"]:  
            correct += 1  
            prog["correct"].add(qid)  
        else:  
            prog["incorrect"].add(qid)  
    prog["marked"].update(st.session_state.test["marked"])  
    save_user_progress(st.session_state.user, prog)  
    tests_ws.append_row([  
        st.session_state.user,  
        st.session_state.test["id"],  
        st.session_state.test["created"],  
        st.session_state.test["mode"],  
        len(st.session_state.test["questions"]),  
        correct,  
        json.dumps(st.session_state.test["systems"]),  
        json.dumps([q["id"] for q in st.session_state.test["questions"]]),  
        json.dumps(st.session_state.test["answers"]),  
        json.dumps(list(st.session_state.test["marked"]))  
    ])  
    delete_ongoing(st.session_state.user)
    total = len(st.session_state.test["questions"])  
    st.metric("Score", f"{correct}/{total}", f"{correct/total*100:.1f}%" if total else "0.0%")  
    if st.button("Review questions"):  
        st.session_state.test["mode"] = "review"  
        st.session_state.test["index"] = 0  
        st.session_state.page = "test"  
        st.rerun()  
    if st.button("🏠 Home"):  
        st.session_state.page = "home"  
        st.rerun()

================= PREVIOUS MENU =================

if st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests Menu")
    if st.button("A. Last test"):
        test_data = load_ongoing(st.session_state.user)
        if test_data:
            st.session_state.test = test_data
            st.session_state.page = "test"
            st.rerun()
        else:
            st.info("No last test found.")
    if st.button("B. Previous tests"):
        st.session_state.page = "previous"
        st.rerun()
    if st.button("C. Analytics"):
        st.session_state.page = "analytics"
        st.rerun()
    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()

================= PREVIOUS =================

if st.session_state.page == "previous":
    st.title("📚 Previous Tests")
    rows = tests_ws.get_all_records()  
    user_tests = [r for r in rows if r.get("username") == st.session_state.user]  
    if not user_tests:  
        st.info("No previous tests found.")  
    else:  
        for i, r in enumerate(user_tests):
            systems = json.loads(r.get("systems_json", "[]"))
            systems_str = "All systems" if "All" in systems else ", ".join(systems)
            expander = st.expander(f"Test {i+1}: {r['created']}, {r['mode']}, {r['total_questions']}Qs, {systems_str}")
            with expander:
                st.write(f"Score: {r['score']}/{r['total_questions']}")
                if st.button("Review", key=f"review_{r['test_id']}_{i}"):
                    q_ids = json.loads(r.get("q_ids_json", "[]"))
                    questions = [ID_TO_Q.get(qid) for qid in q_ids if qid in ID_TO_Q]
                    st.session_state.test = {
                        "id": r["test_id"],
                        "questions": questions,
                        "answers": json.loads(r.get("answers_json", "{}")),
                        "marked": set(json.loads(r.get("marked_json", "[]"))),
                        "index": 0,
                        "mode": "review",
                        "systems": systems,
                        "created": r["created"]
                    }
                    st.session_state.page = "test"
                    st.rerun()
    if st.button("Back to Menu"):
        st.session_state.page = "previous_menu"
        st.rerun()
    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()

================= ANALYTICS =================

if st.session_state.page == "analytics":
    st.title("📈 Analytics")
    prog = get_user_progress(st.session_state.user)
    total = len(QUESTIONS)
    correct = len(prog["correct"])
    incorrect = len(prog["incorrect"])
    unused = total - (correct + incorrect)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Questions", total)
    col2.metric("Unused", unused)
    col3.metric("Correct", correct)
    col4.metric("Incorrect", incorrect)
    fig = px.pie(
        names=["Correct", "Incorrect", "Unused"],
        values=[correct, incorrect, unused],
        title="Question Breakdown"
    )
    st.plotly_chart(fig)
    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()