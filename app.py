import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

# ================= CONFIG =================
st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide")

# ================= GOOGLE SHEETS =================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=SCOPES
)

gc = gspread.authorize(creds)
sh = gc.open(st.secrets["SHEET_NAME"])

users_ws = sh.worksheet("users")
progress_ws = sh.worksheet("progress")
tests_ws = sh.worksheet("tests")

# ================= HELPERS =================
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


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


# ================= SESSION INIT =================
if "page" not in st.session_state:
    st.session_state.page = "login"

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
                st.success("Account created. Please login.")
            else:
                st.error("Username already exists")

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

    if st.button("Start Test"):
        selected = random.sample(pool, min(num_q, len(pool)))

        st.session_state.test = {
            "id": str(uuid.uuid4()),
            "questions": selected,
            "answers": {},
            "marked": set(),
            "index": 0,
            "mode": mode,
            "start": time.time()
        }

        st.session_state.page = "test"
        st.rerun()

# ================= TEST =================
if st.session_state.page == "test":
    test = st.session_state.test
    q = test["questions"][test["index"]]

    st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
    st.markdown(q["question"])

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

    col1, col2, col3 = st.columns(3)

    if col1.button("⬅ Previous") and test["index"] > 0:
        save_current_answer(test, q)
        test["index"] -= 1
        st.rerun()

    if col2.button("Next ➡"):
        save_current_answer(test, q)
        if test["index"] < len(test["questions"]) - 1:
            test["index"] += 1
        else:
            st.session_state.page = "review"
        st.rerun()

    if col3.button("🚩 Mark"):
        test["marked"].add(q["id"])
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

# ================= REVIEW =================
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

    total = len(st.session_state.test["questions"])
    st.metric("Score", f"{correct}/{total}", f"{correct/total*100:.1f}%")

    tests_ws.append_row([
        st.session_state.user,
        st.session_state.test["id"],
        datetime.now().isoformat(),
        st.session_state.test["mode"],
        total,
        correct
    ])

    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()

# ================= PREVIOUS =================
if st.session_state.page == "previous":
    st.title("📚 Previous Tests")

    rows = [
        r for r in tests_ws.get_all_records()
        if r["username"] == st.session_state.user
    ]

    df = pd.DataFrame(rows)

    if df.empty:
        st.info("No previous tests found.")
    else:
        st.dataframe(df)

        fig = px.pie(
            names=["Correct", "Incorrect"],
            values=[
                df["score"].sum(),
                df["total_questions"].sum() - df["score"].sum()
            ],
            title="Overall Performance"
        )
        st.plotly_chart(fig)

    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()