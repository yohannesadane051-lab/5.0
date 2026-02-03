import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Set

# ================= CONFIG =================
st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide", initial_sidebar_state="collapsed")

# ================= CACHED SHEETS CONNECTION =================
@st.cache_resource(ttl=300)  # Cache for 5 minutes to reduce API calls
def get_sheets_connection():
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
    
    return {
        "users": sh.worksheet("users"),
        "progress": sh.worksheet("progress"),
        "tests": sh.worksheet("tests")
    }

# Initialize sheets connection
try:
    sheets = get_sheets_connection()
    users_ws = sheets["users"]
    progress_ws = sheets["progress"]
    tests_ws = sheets["tests"]
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {str(e)}")
    st.stop()

# ================= HELPERS =================
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_all_questions():
    qs = []
    for f in os.listdir():
        if f.endswith(".json"):
            try:
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
                    q["options"] = [v for v in q["options_map"].values() if v]
                    q["answer"] = q["correct_answer"]
                    q["question"] = q["stem"]
                    qs.append(q)
            except Exception as e:
                st.error(f"Error loading {f}: {str(e)}")
                continue
    return qs

QUESTIONS = load_all_questions()
SYSTEMS = sorted(set(q["system"] for q in QUESTIONS))

def get_user_progress(username):
    try:
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
    except Exception as e:
        st.error(f"Error getting user progress: {str(e)}")
        return {"used": set(), "correct": set(), "incorrect": set(), "marked": set()}

def save_user_progress(username, prog):
    try:
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
    except Exception as e:
        st.error(f"Error saving progress: {str(e)}")

def get_user_tests(username):
    try:
        rows = tests_ws.get_all_records()
        user_tests = []
        for r in rows:
            if r.get("username") == username:
                test_data = {}
                test_data_str = r.get("test_data", "{}")
                if test_data_str and test_data_str != "{}":
                    try:
                        test_data = json.loads(test_data_str) if isinstance(test_data_str, str) else test_data_str
                    except:
                        test_data = {}
                
                completed = True 
                if "completed" in r:
                    val = str(r["completed"]).lower()
                    completed = val in ["true", "yes", "1", "completed"]
                
                try:
                    total_questions = int(r.get("total_questions", 0))
                    score = int(r.get("score", 0))
                except:
                    total_questions, score = 0, 0
                
                user_tests.append({
                    "test_id": r.get("test_id", ""),
                    "created": r.get("created", ""),
                    "mode": r.get("mode", ""),
                    "total_questions": total_questions,
                    "score": score,
                    "system": r.get("system", "All"),
                    "answers": test_data.get("answers", {}),
                    "questions": test_data.get("questions", []),
                    "index": test_data.get("index", 0),
                    "marked": set(test_data.get("marked", [])),
                    "completed": completed
                })
        
        def get_sortable_date(test_obj):
            d = test_obj.get("created", "")
            if not d: return datetime.min
            try:
                return datetime.fromisoformat(str(d).replace('Z', '+00:00'))
            except:
                for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"]:
                    try: return datetime.strptime(str(d), fmt)
                    except: continue
            return datetime.min
        
        return sorted(user_tests, key=get_sortable_date, reverse=True)
    except Exception as e:
        st.error(f"Error getting user tests: {str(e)}")
        return []

def save_test_session(username, test, completed=True):
    try:
        systems_in_test = set(q["system"] for q in test["questions"])
        system_str = ", ".join(sorted(systems_in_test)) if len(systems_in_test) <= 3 else "Multiple"
        score = sum(1 for q in test["questions"] if test["answers"].get(q["id"]) == q["answer"])
        
        test_data = {
            "answers": test["answers"],
            "questions": [{"id": q["id"], "question": q["question"][:500], "answer": q["answer"]} for q in test["questions"]],
            "index": test["index"],
            "marked": list(test["marked"])
        }
        
        current_time = datetime.now().isoformat()
        try:
            cell_list = tests_ws.findall(test["id"])
            if cell_list:
                row = cell_list[0].row
                tests_ws.update(f"C{row}:I{row}", [[current_time, test["mode"], len(test["questions"]), score, system_str, json.dumps(test_data), str(completed).lower()]])
            else:
                tests_ws.append_row([username, test["id"], current_time, test["mode"], len(test["questions"]), score, system_str, json.dumps(test_data), str(completed).lower()])
        except:
            tests_ws.append_row([username, test["id"], current_time, test["mode"], len(test["questions"]), score, system_str, json.dumps(test_data), str(completed).lower()])
        return True
    except Exception as e:
        st.error(f"Error saving test session: {str(e)}")
        return False

def save_current_answer(test, q):
    if "current_choice" in st.session_state and st.session_state.current_choice:
        for k, v in q["options_map"].items():
            if v == st.session_state.current_choice:
                test["answers"][q["id"]] = k
                break

def calculate_total_test_time(num_questions):
    return num_questions * 90

def format_time(seconds):
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

def update_timer(test):
    if test.get("mode") == "Test" and "start" in test:
        elapsed = int(time.time() - test["start"])
        rem = max(0, calculate_total_test_time(len(test["questions"])) - elapsed)
        st.session_state.timer_elapsed, st.session_state.timer_remaining = elapsed, rem
        if rem <= 0 and not test.get("is_review"):
            st.session_state.time_up = True
            return True
    return False

# ================= SESSION STATE =================
for key, val in {"page": "login", "user": None, "test": None, "navigation_history": [], "timer_elapsed": 0, "timer_remaining": 0, "time_up": False}.items():
    if key not in st.session_state: st.session_state[key] = val

def navigate_to(page):
    st.session_state.navigation_history.append(st.session_state.page)
    st.session_state.page = page
    st.rerun()

def go_back():
    st.session_state.page = st.session_state.navigation_history.pop() if st.session_state.navigation_history else "home"
    st.rerun()

# ================= AUTH =================
def login(u, p):
    try:
        return any(r["username"] == u and r["password_hash"] == hash_pw(p) for r in users_ws.get_all_records())
    except: return False

def signup(u, p):
    try:
        if any(r["username"] == u for r in users_ws.get_all_records()): return False
        users_ws.append_row([u, hash_pw(p), datetime.now().isoformat()])
        progress_ws.append_row([u, "[]", "[]", "[]", "[]"])
        return True
    except: return False

# ================= ROUTING =================
if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")
    t1, t2 = st.tabs(["Login", "Sign Up"])
    with t1:
        u, p = st.text_input("Username"), st.text_input("Password", type="password")
        if st.button("Login"):
            if login(u, p):
                st.session_state.user, st.session_state.page = u, "home"
                st.rerun()
            else: st.error("Invalid credentials")
    with t2:
        nu, np = st.text_input("New username"), st.text_input("New password", type="password")
        if st.button("Create Account"):
            if signup(nu, np): st.success("Account created. Please login.")
            else: st.error("Username already exists")
    st.stop()

if st.session_state.page == "home":
    st.sidebar.title(f"👤 {st.session_state.user}")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()
    user_tests = get_user_tests(st.session_state.user)
    incomplete = [t for t in user_tests if not t.get("completed", True)]
    st.title("🏠 Home")
    c1, c2 = st.columns(2)
    if c1.button("🧪 Create New Test", use_container_width=True): navigate_to("create")
    if c2.button("📚 Previous Tests & Analytics", use_container_width=True): navigate_to("previous_menu")
    if incomplete:
        st.divider()
        st.subheader("Continue Last Session")
        t = incomplete[0]
        st.write(f"**Mode:** {t['mode']} | **Progress:** {t['index'] + 1}/{t['total_questions']}")
        if st.button("➡️ Continue Last Test"):
            qs = []
            for qd in t["questions"]:
                match = next((oq for oq in QUESTIONS if oq["id"] == qd.get("id")), None)
                qs.append(match if match else {"id": qd.get("id"), "question": qd.get("question"), "options_map": {"A": "A", "B": "B", "C": "C", "D": "D"}, "options": ["A", "B", "C", "D"], "answer": "A"})
            st.session_state.test = {"id": t["test_id"], "questions": qs, "answers": t["answers"], "marked": t["marked"], "index": t["index"], "mode": t["mode"], "start": time.time(), "is_review": False}
            st.session_state.page = "test"
            st.rerun()
    st.stop()

if st.session_state.page == "previous_menu":
    st.title("📚 History & Analytics")
    if st.button("← Back"): go_back()
    tab1, tab2 = st.tabs(["📋 Previous Tests", "📊 Analytics"])
    with tab1:
        ut = get_user_tests(st.session_state.user)
        if not ut: st.info("No tests found.")
        else:
            for i, t in enumerate(ut):
                d_obj = None
                try: d_obj = datetime.fromisoformat(t['created'].replace('Z', '+00:00'))
                except: pass
                d_str = d_obj.strftime("%b %d, %Y %I:%M %p") if d_obj else t['created']
                label = f"{'✅' if t['completed'] else '⚠️'} {d_str} - {t['mode']} ({t['score']}/{t['total_questions']})"
                with st.expander(label):
                    st.write(f"**System:** {t['system']}")
                    if st.button("Review" if t['completed'] else "Continue", key=f"hist_{i}"):
                        qs = []
                        for qd in t["questions"]:
                            match = next((oq for oq in QUESTIONS if oq["id"] == qd.get("id")), None)
                            qs.append(match if match else {"id": qd.get("id"), "question": qd.get("question"), "options_map": {"A": "A", "B": "B", "C": "C", "D": "D"}, "options": ["A", "B", "C", "D"], "answer": "A"})
                        st.session_state.test = {"id": t["test_id"], "questions": qs, "answers": t["answers"], "marked": t["marked"], "index": 0 if t['completed'] else t['index'], "mode": t["mode"], "is_review": t['completed']}
                        st.session_state.page = "test_review" if t['completed'] else "test"
                        st.rerun()
    st.stop()

if st.session_state.page == "create":
    st.title("🧪 Create New Test")
    if st.button("← Back"): go_back()
    prog = get_user_progress(st.session_state.user)
    num_q = st.slider("Number of questions", 1, 50, 20)
    mode = st.radio("Mode", ["Reading", "Test"])
    systems = st.multiselect("Systems", ["All"] + SYSTEMS, default="All")
    pool = [q for q in QUESTIONS if "All" in systems or q["system"] in systems]
    st.info(f"Available questions: {len(pool)}")
    if mode == "Test":
        ts = calculate_total_test_time(num_q)
        st.info(f"Estimated test time: {ts//60} minutes ({num_q} questions × 90s)")
    if st.button("Start Test", use_container_width=True):
        if len(pool) < num_q: st.error("Not enough questions.")
        else:
            sel = random.sample(pool, num_q)
            st.session_state.test = {"id": str(uuid.uuid4()), "questions": sel, "answers": {}, "marked": set(), "index": 0, "mode": mode, "start": time.time(), "is_review": False}
            save_test_session(st.session_state.user, st.session_state.test, False)
            st.session_state.page = "test"
            st.rerun()
    st.stop()

if st.session_state.page == "test":
    # CRITICAL: This empty block prevents Create Test elements from persisting
    main_container = st.empty()
    with main_container.container():
        test = st.session_state.test
        q = test["questions"][test["index"]]
        if test["mode"] == "Test" and not test.get("is_review"):
            if update_timer(test):
                save_current_answer(test, q)
                save_test_session(st.session_state.user, test, True)
                st.session_state.page = "review"
                st.rerun()
        
        c1, c2, c3 = st.columns([1, 3, 1])
        c1.write(f"**Mode:** {test['mode']}")
        c2.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
        if test["mode"] == "Test":
            c3.metric("Time", format_time(st.session_state.timer_remaining))
        if st.button("🏠 Save & Exit"):
            save_current_answer(test, q)
            save_test_session(st.session_state.user, test, False)
            st.session_state.page = "home"
            st.rerun()
            
        st.divider()
        st.markdown(f"### {q['question']}")
        cur_ans = q["options_map"].get(test["answers"].get(q["id"]))
        choice = st.radio("Select answer", q["options"], index=q["options"].index(cur_ans) if cur_ans in q["options"] else None, key=f"q_{test['index']}")
        if choice:
            st.session_state.current_choice = choice
            save_current_answer(test, q)
            
        st.divider()
        nc1, nc2, nc3 = st.columns(3)
        if nc1.button("⬅ Previous", disabled=test["index"]==0):
            test["index"] -= 1
            st.rerun()
        if nc2.button("Next ➡" if test["index"] < len(test["questions"])-1 else "Finish"):
            if test["index"] < len(test["questions"])-1:
                test["index"] += 1
                st.rerun()
            else:
                st.session_state.page = "review"
                st.rerun()
        if nc3.button("🚩 Mark" if q["id"] not in test["marked"] else "✅ Unmark"):
            if q["id"] in test["marked"]: test["marked"].remove(q["id"])
            else: test["marked"].add(q["id"])
            st.rerun()
            
        if test["mode"] == "Reading" and choice:
            st.info(f"**Correct Answer:** {q['answer']} \n\n **Explanation:** {q.get('explanation', 'N/A')}")
        
        if test["mode"] == "Test":
            time.sleep(1)
            st.rerun()
    st.stop()

if st.session_state.page == "review":
    st.title("📊 Test Results")
    test = st.session_state.test
    prog = get_user_progress(st.session_state.user)
    correct = 0
    for q in test["questions"]:
        qid = q["id"]
        prog["used"].add(qid)
        if test["answers"].get(qid) == q["answer"]:
            correct += 1
            prog["correct"].add(qid)
        else:
            prog["incorrect"].add(qid)
    save_user_progress(st.session_state.user, prog)
    save_test_session(st.session_state.user, test, True)
    st.metric("Score", f"{correct}/{len(test['questions'])}", f"{(correct/len(test['questions']))*100:.1f}%")
    if st.button("🏠 Home"): st.session_state.page = "home"; st.rerun()
    st.stop()
