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
        # If user not found, create entry
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
        rows = tests_ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
        user_tests = []
        for r in rows:
            if r.get("username") == username:
                test_data = {}
                test_data_str = r.get("test_data", "{}")
                
                if test_data_str and test_data_str != "{}":
                    try:
                        if isinstance(test_data_str, str):
                            test_data = json.loads(test_data_str)
                        else:
                            test_data = test_data_str
                    except:
                        test_data = {}
                
                completed = True 
                if "completed" in r:
                    completed_val = r["completed"]
                    if isinstance(completed_val, str):
                        completed = completed_val.lower() in ["true", "yes", "1", "completed"]
                    elif isinstance(completed_val, bool):
                        completed = completed_val
                    elif isinstance(completed_val, (int, float)):
                        completed = bool(completed_val)
                
                try:
                    total_questions = int(r.get("total_questions", 0))
                    score = int(r.get("score", 0))
                except:
                    total_questions = 0
                    score = 0
                
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
            created_str = test_obj.get("created", "")
            if not created_str:
                return datetime.min
            try:
                serial = float(created_str)
                return datetime(1899, 12, 30) + timedelta(days=serial)
            except:
                pass
            try:
                created_str = str(created_str).strip().strip('"\' ')
                created_date = None
                if 'T' in created_str:
                    if created_str.endswith('Z'):
                        created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                    else:
                        if '+' in created_str or '-' in created_str[-6:]:
                            created_date = datetime.fromisoformat(created_str)
                        else:
                            created_date = datetime.fromisoformat(created_str + '+00:00')
                else:
                    date_formats = [
                        "%Y-%m-%d %H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d",
                        "%m/%d/%Y %H:%M:%S",
                        "%m/%d/%Y",
                        "%d/%m/%Y %H:%M:%S",
                        "%d/%m/%Y",
                        "%Y-%m-%dT%H:%M:%S.%f%z",
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %I:%M:%S %p",
                        "%Y-%m-%d %I:%M %p",
                        "%m/%d/%Y %I:%M:%S %p",
                        "%m/%d/%Y %I:%M %p",
                        "%d/%m/%Y %I:%M:%S %p",
                        "%d/%m/%Y %I:%M %p",
                    ]
                    for fmt in date_formats:
                        try:
                            created_date = datetime.strptime(created_str, fmt)
                            break
                        except ValueError:
                            continue
                if created_date:
                    return created_date
            except:
                pass
            return datetime.min
        
        return sorted(user_tests, key=get_sortable_date, reverse=True)
    except Exception as e:
        st.error(f"Error getting user tests: {str(e)}")
        return []

def save_test_session(username, test, completed=True):
    try:
        systems_in_test = set(q["system"] for q in test["questions"])
        system_str = ", ".join(sorted(systems_in_test)) if len(systems_in_test) <= 3 else "Multiple"
        
        score = 0
        for q in test["questions"]:
            if test["answers"].get(q["id"]) == q["answer"]:
                score += 1
        
        test_data = {
            "answers": test["answers"],
            "questions": [
                {
                    "id": q["id"],
                    "question": q["question"][:500] if len(q["question"]) > 500 else q["question"],
                    "answer": q["answer"],
                    "explanation": q.get("explanation", "")[:500] if q.get("explanation") and len(q.get("explanation", "")) > 500 else q.get("explanation", "")
                }
                for q in test["questions"]
            ],
            "index": test["index"],
            "marked": list(test["marked"])
        }
        
        current_time = datetime.now()
        
        try:
            cell_list = tests_ws.findall(test["id"])
            if cell_list:
                cell = cell_list[0]
                row = cell.row
                tests_ws.update(f"D{row}:I{row}", [[
                    test["mode"],
                    len(test["questions"]),
                    score,
                    system_str,
                    json.dumps(test_data),
                    str(completed).lower()
                ]])
            else:
                tests_ws.append_row([
                    username,
                    test["id"],
                    current_time.isoformat(),
                    test["mode"],
                    len(test["questions"]),
                    score,
                    system_str,
                    json.dumps(test_data),
                    str(completed).lower()
                ])
        except Exception as e:
            tests_ws.append_row([
                username,
                test["id"],
                current_time.isoformat(),
                test["mode"],
                len(test["questions"]),
                score,
                system_str,
                json.dumps(test_data),
                str(completed).lower()
            ])
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
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def update_timer(test):
    if test.get("mode") == "Test" and "start" in test:
        elapsed = int(time.time() - test["start"])
        total_time = calculate_total_test_time(len(test["questions"]))
        remaining = max(0, total_time - elapsed)
        st.session_state.timer_elapsed = elapsed
        st.session_state.timer_remaining = remaining
        if remaining <= 0 and not test.get("is_review"):
            st.session_state.time_up = True
            return True
    return False

if "page" not in st.session_state:
    st.session_state.page = "login"
if "user" not in st.session_state:
    st.session_state.user = None
if "test" not in st.session_state:
    st.session_state.test = None
if "last_test_id" not in st.session_state:
    st.session_state.last_test_id = None
if "navigation_history" not in st.session_state:
    st.session_state.navigation_history = []
if "timer_elapsed" not in st.session_state:
    st.session_state.timer_elapsed = 0
if "timer_remaining" not in st.session_state:
    st.session_state.timer_remaining = 0
if "time_up" not in st.session_state:
    st.session_state.time_up = False
if "clear_cache_on_test" not in st.session_state:
    st.session_state.clear_cache_on_test = False

def navigate_to(page):
    st.session_state.navigation_history.append(st.session_state.page)
    st.session_state.page = page
    if page == "test":
        st.session_state.clear_cache_on_test = True
    st.rerun()

def go_back():
    if st.session_state.navigation_history:
        st.session_state.page = st.session_state.navigation_history.pop()
        st.rerun()
    else:
        st.session_state.page = "home"
        st.rerun()

def login(username, pw):
    try:
        for r in users_ws.get_all_records():
            if r["username"] == username and r["password_hash"] == hash_pw(pw):
                return True
        return False
    except Exception as e:
        st.error(f"Login error: {str(e)}")
        return False

def signup(username, pw):
    try:
        if any(r["username"] == username for r in users_ws.get_all_records()):
            return False
        users_ws.append_row([username, hash_pw(pw), datetime.now().isoformat()])
        progress_ws.append_row([username, "[]", "[]", "[]", "[]"])
        return True
    except Exception as e:
        st.error(f"Signup error: {str(e)}")
        return False

if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")
    if st.session_state.user:
        if st.button("↩️ Return to Session"):
            st.session_state.page = "home"
            st.rerun()
    t1, t2 = st.tabs(["Login", "Sign Up"])
    with t1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            if login(u, p):
                st.session_state.user = u
                st.session_state.page = "home"
                st.session_state.navigation_history = []
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

if st.session_state.page == "home":
    st.sidebar.title(f"👤 {st.session_state.user}")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.session_state.page = "login"
        st.rerun()
    user_tests = get_user_tests(st.session_state.user)
    incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
    last_incomplete_test = incomplete_tests[0] if incomplete_tests else None
    st.title("🏠 Home")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧪 Create New Test", use_container_width=True):
            navigate_to("create")
    with col2:
        if st.button("📚 Previous Tests & Analytics", use_container_width=True):
            navigate_to("previous_menu")
    if last_incomplete_test:
        st.divider()
        st.subheader("Continue Last Session")
        st.write(f"**Mode:** {last_incomplete_test['mode']}")
        st.write(f"**Progress:** Question {last_incomplete_test['index'] + 1}/{last_incomplete_test['total_questions']}")
        if st.button("➡️ Continue Last Test", key="continue_last_home"):
            restored_questions = []
            for q_data in last_incomplete_test["questions"]:
                found = False
                for original_q in QUESTIONS:
                    if original_q["id"] == q_data.get("id"):
                        restored_questions.append(original_q)
                        found = True
                        break
                if not found:
                    restored_questions.append({
                        "id": q_data.get("id", ""),
                        "system": "Unknown",
                        "question": q_data.get("question", "Question not found"),
                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                        "options": ["Option A", "Option B", "Option C", "Option D"],
                        "answer": q_data.get("answer", "A"),
                        "explanation": q_data.get("explanation", "")
                    })
            if restored_questions:
                st.session_state.test = {
                    "id": last_incomplete_test["test_id"],
                    "questions": restored_questions,
                    "answers": last_incomplete_test["answers"],
                    "marked": last_incomplete_test["marked"],
                    "index": last_incomplete_test["index"],
                    "mode": last_incomplete_test["mode"],
                    "start": time.time(),
                    "is_review": False
                }
                st.session_state.page = "test"
                st.rerun()
    st.stop()

if st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests & Analytics")
    if st.button("← Back"):
        go_back()
    tab1, tab2, tab3 = st.tabs(["📋 Previous Tests", "📊 Analytics", "▶️ Last Test"])
    with tab1:
        st.subheader("Your Test History")
        user_tests = get_user_tests(st.session_state.user)
        if not user_tests:
            st.info("No tests found yet. Create your first test!")
        else:
            completed_tests = [t for t in user_tests if t.get("completed", True)]
            incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
            if incomplete_tests:
                st.write(f"**Incomplete Tests ({len(incomplete_tests)})**")
                for i, test in enumerate(incomplete_tests):
                    with st.expander(f"⚠️ Incomplete Test {i+1}: {test.get('mode', 'Unknown')} Mode", expanded=(i==0)):
                        formatted_date = "Unknown date"
                        created_str = test.get("created", "")
                        if created_str:
                            try:
                                serial = float(created_str)
                                created_date = datetime(1899, 12, 30) + timedelta(days=serial)
                            except:
                                pass
                            else:
                                formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                            if 'created_date' not in locals() or not created_date:
                                created_str = str(created_str).strip('"\' ')
                                created_date = None
                                try:
                                    if 'T' in created_str:
                                        if created_str.endswith('Z'):
                                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                        else:
                                            if '+' in created_str or '-' in created_str[-6:]:
                                                created_date = datetime.fromisoformat(created_str)
                                            else:
                                                created_date = datetime.fromisoformat(created_str + '+00:00')
                                    else:
                                        date_formats = [
                                            "%Y-%m-%d %H:%M:%S.%f",
                                            "%Y-%m-%d %H:%M:%S",
                                            "%Y-%m-%d",
                                            "%m/%d/%Y %H:%M:%S",
                                            "%m/%d/%Y",
                                            "%d/%m/%Y %H:%M:%S",
                                            "%d/%m/%Y",
                                            "%Y-%m-%dT%H:%M:%S.%f%z",
                                            "%Y-%m-%dT%H:%M:%S%z",
                                            "%Y-%m-%dT%H:%M:%S.%f",
                                            "%Y-%m-%dT%H:%M:%S",
                                            "%Y-%m-%d %I:%M:%S %p",
                                            "%Y-%m-%d %I:%M %p",
                                            "%m/%d/%Y %I:%M:%S %p",
                                            "%m/%d/%Y %I:%M %p",
                                            "%d/%m/%Y %I:%M:%S %p",
                                            "%d/%m/%Y %I:%M %p",
                                        ]
                                        for fmt in date_formats:
                                            try:
                                                created_date = datetime.strptime(created_str, fmt)
                                                break
                                            except:
                                                continue
                                except:
                                    pass
                                if created_date:
                                    formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                                else:
                                    formatted_date = created_str
                        st.write(f"**Date:** {formatted_date}")
                        st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
                        st.write(f"**Progress:** Question {test['index'] + 1}/{test['total_questions']}")
                        st.write(f"**System:** {test.get('system', 'All')}")
                        if st.button(f"Continue This Test", key=f"continue_{i}"):
                            restored_questions = []
                            for q_data in test["questions"]:
                                found = False
                                for original_q in QUESTIONS:
                                    if original_q["id"] == q_data.get("id"):
                                        restored_questions.append(original_q)
                                        found = True
                                        break
                                if not found:
                                    restored_questions.append({
                                        "id": q_data.get("id", ""),
                                        "system": "Unknown",
                                        "question": q_data.get("question", "Question not found"),
                                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                        "options": ["Option A", "Option B", "Option C", "Option D"],
                                        "answer": q_data.get("answer", "A"),
                                        "explanation": q_data.get("explanation", "")
                                    })
                            if restored_questions:
                                st.session_state.test = {
                                    "id": test["test_id"],
                                    "questions": restored_questions,
                                    "answers": test["answers"],
                                    "marked": test["marked"],
                                    "index": test["index"],
                                    "mode": test["mode"],
                                    "start": time.time(),
                                    "is_review": False
                                }
                                st.session_state.page = "test"
                                st.rerun()
                st.divider()
            if completed_tests:
                st.write(f"**Completed Tests ({len(completed_tests)})**")
                for i, test in enumerate(completed_tests):
                    total_time = ""
                    try:
                        if "start_time" in test:
                            total_time = f" | Time: {format_time(test.get('duration', 0))}"
                    except:
                        pass
                    with st.expander(f"Test {i+1}: {test.get('mode', 'Unknown')} Mode - Score: {test['score']}/{test['total_questions']}{total_time}"):
                        formatted_date = "Unknown date"
                        created_str = test.get("created", "")
                        if created_str:
                            try:
                                serial = float(created_str)
                                created_date = datetime(1899, 12, 30) + timedelta(days=serial)
                            except:
                                pass
                            else:
                                formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                            if 'created_date' not in locals() or not created_date:
                                created_str = str(created_str).strip('"\' ")
                                created_date = None
                                try:
                                    if 'T' in created_str:
                                        if created_str.endswith('Z'):
                                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                        else:
                                            if '+' in created_str or '-' in created_str[-6:]:
                                                created_date = datetime.fromisoformat(created_str)
                                            else:
                                                created_date = datetime.fromisoformat(created_str + '+00:00')
                                    else:
                                        date_formats = [
                                            "%Y-%m-%d %H:%M:%S.%f",
                                            "%Y-%m-%d %H:%M:%S",
                                            "%Y-%m-%d",
                                            "%m/%d/%Y %H:%M:%S",
                                            "%m/%d/%Y",
                                            "%d/%m/%Y %H:%M:%S",
                                            "%d/%m/%Y",
                                            "%Y-%m-%dT%H:%M:%S.%f%z",
                                            "%Y-%m-%dT%H:%M:%S%z",
                                            "%Y-%m-%dT%H:%M:%S.%f",
                                            "%Y-%m-%dT%H:%M:%S",
                                            "%Y-%m-%d %I:%M:%S %p",
                                            "%Y-%m-%d %I:%M %p",
                                            "%m/%d/%Y %I:%M:%S %p",
                                            "%m/%d/%Y %I:%M %p",
                                            "%d/%m/%Y %I:%M:%S %p",
                                            "%d/%m/%Y %I:%M %p",
                                        ]
                                        for fmt in date_formats:
                                            try:
                                                created_date = datetime.strptime(created_str, fmt)
                                                break
                                            except:
                                                continue
                                except:
                                    pass
                                if created_date:
                                    formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                                else:
                                    formatted_date = created_str
                        st.write(f"**Date:** {formatted_date}")
                        st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
                        st.write(f"**Questions:** {test['total_questions']}")
                        if test['total_questions'] > 0:
                            score_percentage = (test['score'] / test['total_questions']) * 100
                            st.write(f"**Score:** {test['score']}/{test['total_questions']} ({score_percentage:.1f}%)")
                        else:
                            st.write(f"**Score:** {test['score']}/{test['total_questions']} (N/A%)")
                        st.write(f"**System:** {test.get('system', 'All')}")
                        if st.button(f"Review This Test", key=f"review_{i}"):
                            restored_questions = []
                            for q_data in test["questions"]:
                                found = False
                                for original_q in QUESTIONS:
                                    if original_q["id"] == q_data.get("id"):
                                        restored_questions.append(original_q)
                                        found = True
                                        break
                                if not found:
                                    restored_questions.append({
                                        "id": q_data.get("id", ""),
                                        "system": "Unknown",
                                        "question": q_data.get("question", "Question not found"),
                                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                        "options": ["Option A", "Option B", "Option C", "Option D"],
                                        "answer": q_data.get("answer", "A"),
                                        "explanation": q_data.get("explanation", "")
                                    })
                            if restored_questions:
                                st.session_state.test = {
                                    "id": test["test_id"],
                                    "questions": restored_questions,
                                    "answers": test["answers"],
                                    "marked": test["marked"],
                                    "index": 0,
                                    "mode": test["mode"],
                                    "is_review": True
                                }
                                st.session_state.page = "test_review"
                                st.rerun()
            elif not incomplete_tests:
                st.info("No tests found. Create your first test!")
    with tab2:
        st.subheader("📊 Your Analytics")
        prog = get_user_progress(st.session_state.user)
        user_tests = get_user_tests(st.session_state.user)
        completed_tests = [t for t in user_tests if t.get("completed", True)]
        col1, col2, col3, col4 = st.columns(4)
        total_questions = len(QUESTIONS)
        used_questions = len(prog["used"])
        unused_questions = total_questions - used_questions
        correct_questions = len(prog["correct"])
        incorrect_questions = len(prog["incorrect"])
        with col1:
            st.metric("Total Questions", total_questions)
        with col2:
            st.metric("Unused Questions", unused_questions)
        with col3:
            st.metric("Correct", correct_questions)
        with col4:
            st.metric("Incorrect", incorrect_questions)
        if total_questions > 0:
            usage_percent = (used_questions / total_questions) * 100
            st.progress(usage_percent / 100)
            st.write(f"**Question Usage:** {used_questions}/{total_questions} ({usage_percent:.1f}%)")
        else:
            st.progress(0)
            st.write("**Question Usage:** 0/0 (0%)")
        if used_questions > 0:
            fig = go.Figure(data=[go.Pie(labels=['Correct', 'Incorrect'], values=[correct_questions, incorrect_questions], hole=0.3, marker_colors=['green', 'red'])])
            fig.update_layout(title_text="Question Performance")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No questions answered yet. Start a test to see performance analytics.")
        if completed_tests:
            st.subheader("Test History")
            dates = []
            scores = []
            for test in completed_tests[-10:]:
                try:
                    created_date = None
                    created_str = test.get("created", "")
                    if created_str:
                        created_str = str(created_str).strip()
                        try:
                            serial = float(created_str)
                            created_date = datetime(1899, 12, 30) + timedelta(days=serial)
                        except:
                            pass
                        if not created_date:
                            try:
                                if 'T' in created_str:
                                    if created_str.endswith('Z'):
                                        created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                    else:
                                        if '+' in created_str or '-' in created_str[-6:]:
                                            created_date = datetime.fromisoformat(created_str)
                                        else:
                                            created_date = datetime.fromisoformat(created_str + '+00:00')
                                else:
                                    date_formats = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p"]
                                    for fmt in date_formats:
                                        try:
                                            created_date = datetime.strptime(created_str, fmt)
                                            break
                                        except:
                                            continue
                                if created_date:
                                    date_str = created_date.strftime("%m/%d")
                                    dates.append(date_str)
                                    if test["total_questions"] > 0:
                                        percentage = (test["score"] / test["total_questions"]) * 100
                                    else:
                                        percentage = 0
                                    scores.append(percentage)
                            except:
                                continue
                except Exception as e:
                    continue
            if dates and scores:
                fig2 = go.Figure(data=[go.Scatter(x=dates, y=scores, mode='lines+markers', name='Score %')])
                fig2.update_layout(title="Recent Test Performance", xaxis_title="Test Date", yaxis_title="Score %", yaxis_range=[0, 100])
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Not enough test data to display performance chart.")
    with tab3:
        st.subheader("▶️ Continue Last Test")
        user_tests = get_user_tests(st.session_state.user)
        incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
        if incomplete_tests:
            test = incomplete_tests[0]
            formatted_date = "Unknown date"
            created_str = test.get("created", "")
            if created_str:
                try:
                    serial = float(created_str)
                    created_date = datetime(1899, 12, 30) + timedelta(days=serial)
                except:
                    pass
                else:
                    formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                if 'created_date' not in locals() or not created_date:
                    created_str = str(created_str).strip('"\' ")
                    created_date = None
                    try:
                        if 'T' in created_str:
                            if created_str.endswith('Z'):
                                created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                            else:
                                if '+' in created_str or '-' in created_str[-6:]:
                                    created_date = datetime.fromisoformat(created_str)
                                else:
                                    created_date = datetime.fromisoformat(created_str + '+00:00')
                        else:
                            date_formats = [
                                "%Y-%m-%d %H:%M:%S.%f",
                                "%Y-%m-%d %H:%M:%S",
                                "%Y-%m-%d",
                                "%m/%d/%Y %H:%M:%S",
                                "%m/%d/%Y",
                                "%d/%m/%Y %H:%M:%S",
                                "%d/%m/%Y",
                                "%Y-%m-%dT%H:%M:%S.%f%z",
                                "%Y-%m-%dT%H:%M:%S%z",
                                "%Y-%m-%dT%H:%M:%S.%f",
                                "%Y-%m-%dT%H:%M:%S",
                                "%Y-%m-%d %I:%M:%S %p",
                                "%Y-%m-%d %I:%M %p",
                                "%m/%d/%Y %I:%M:%S %p",
                                "%m/%d/%Y %I:%M %p",
                                "%d/%m/%Y %I:%M:%S %p",
                                "%d/%m/%Y %I:%M %p",
                            ]
                            for fmt in date_formats:
                                try:
                                    created_date = datetime.strptime(created_str, fmt)
                                    break
                                except:
                                    continue
                    except:
                        pass
                    if created_date:
                        formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                    else:
                        formatted_date = created_str
            st.write(f"**Last Incomplete Test**")
            st.write(f"**Date:** {formatted_date}")
            st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
            st.write(f"**Progress:** Question {test['index'] + 1}/{test['total_questions']}")
            st.write(f"**System:** {test.get('system', 'All')}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Continue Test", use_container_width=True):
                    restored_questions = []
                    for q_data in test["questions"]:
                        found = False
                        for original_q in QUESTIONS:
                            if original_q["id"] == q_data.get("id"):
                                restored_questions.append(original_q)
                                found = True
                                break
                        if not found:
                            restored_questions.append({
                                "id": q_data.get("id", ""),
                                "system": "Unknown",
                                "question": q_data.get("question", "Question not found"),
                                "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                "options": ["Option A", "Option B", "Option C", "Option D"],
                                "answer": q_data.get("answer", "A"),
                                "explanation": q_data.get("explanation", "")
                            })
                    if restored_questions:
                        st.session_state.test = {
                            "id": test["test_id"],
                            "questions": restored_questions,
                            "answers": test["answers"],
                            "marked": test["marked"],
                            "index": test["index"],
                            "mode": test["mode"],
                            "start": time.time(),
                            "is_review": False
                        }
                        st.session_state.page = "test"
                        st.rerun()
            with col2:
                if st.button("Start New Test Instead", use_container_width=True):
                    st.session_state.page = "create"
                    st.rerun()
        else:
            st.info("No incomplete tests found. All tests are completed!")
            if st.button("Create New Test", use_container_width=True):
                st.session_state.page = "create"
                st.rerun()
    st.stop()

if st.session_state.page == "create":
    st.title("🧪 Create New Test")
    if st.button("← Back"):
        go_back()
    prog = get_user_progress(st.session_state.user)
    num_q = st.slider("Number of questions", 1, 50, 20)
    mode = st.radio("Mode", ["Reading", "Test"])
    systems = st.multiselect("Systems", ["All"] + SYSTEMS, default="All")
    filters = st.multiselect("Filters", ["All", "Unused", "Correct", "Incorrect", "Marked"], default="All")
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
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            go_back()
    with col2:
        if st.button("Start Test", use_container_width=True):
            if len(pool) < num_q:
                st.error(f"Not enough questions available. Only {len(pool)} questions match your criteria.")
            else:
                selected = random.sample(pool, min(num_q, len(pool)))
                st.session_state.test = {
                    "id": str(uuid.uuid4()),
                    "questions": selected,
                    "answers": {},
                    "marked": set(),
                    "index": 0,
                    "mode": mode,
                    "start": time.time(),
                    "is_review": False
                }
                save_test_session(st.session_state.user, st.session_state.test, completed=False)
                st.session_state.page = "test"
                st.rerun()
    st.stop()

if st.session_state.page == "test":
    if st.session_state.get("clear_cache_on_test", False):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.session_state.clear_cache_on_test = False
        st.rerun()
    if st.session_state.test is None:
        st.error("No test session found. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
    test = st.session_state.test
    q = test["questions"][test["index"]]
    if test["mode"] == "Test" and not test.get("is_review"):
        time_up = update_timer(test)
        if time_up or st.session_state.time_up:
            save_current_answer(test, q)
            save_test_session(st.session_state.user, test, completed=True)
            st.session_state.page = "review"
            st.rerun()
    if test["mode"] == "Test" and not test.get("is_review"):
        col_head1, col_head2, col_head3, col_head4 = st.columns([2, 3, 2, 1])
        with col_head1:
            st.write(f"**Mode:** {test['mode']}")
        with col_head2:
            st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
        with col_head3:
            elapsed_str = format_time(st.session_state.timer_elapsed)
            remaining_str = format_time(st.session_state.timer_remaining)
            total_time = calculate_total_test_time(len(test["questions"]))
            warning_threshold = total_time * 0.1
            if st.session_state.timer_remaining <= warning_threshold:
                st.warning(f"⏰ Time: {elapsed_str} | Remaining: {remaining_str}")
            else:
                st.info(f"⏰ Time: {elapsed_str} | Remaining: {remaining_str}")
        with col_head4:
            if st.button("🏠 End & Save", type="secondary", use_container_width=True):
                save_current_answer(test, q)
                save_test_session(st.session_state.user, test, completed=False)
                st.session_state.page = "home"
                st.rerun()
    else:
        col_head1, col_head2, col_head3 = st.columns([2, 3, 1])
        with col_head1:
            st.write(f"**Mode:** {test['mode']}")
        with col_head2:
            st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
        with col_head3:
            if st.button("🏠 End & Save", type="secondary", use_container_width=True):
                save_current_answer(test, q)
                save_test_session(st.session_state.user, test, completed=False)
                st.session_state.page = "home"
                st.rerun()
    st.divider()
    st.markdown(f"**{q['question']}**")
    radio_key = f"q_{q['id']}_answer_{test['index']}"
    current_answer = None
    if q["id"] in test["answers"]:
        current_answer = q["options_map"][test["answers"][q["id"]]]
    choice = st.radio("Select answer", q["options"], index=q["options"].index(current_answer) if current_answer in q["options"] else None, key=radio_key)
    if choice:
        st.session_state.current_choice = choice
        save_current_answer(test, q)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("⬅ Previous", use_container_width=True, disabled=test["index"] == 0):
            save_current_answer(test, q)
            test["index"] -= 1
            st.rerun()
    with col2:
        next_text = "Finish" if test["index"] == len(test["questions"]) - 1 else "Next ➡"
        if st.button(next_text, use_container_width=True):
            save_current_answer(test, q)
            if test["index"] < len(test["questions"]) - 1:
                test["index"] += 1
                st.rerun()
            else:
                st.session_state.page = "review"
                st.rerun()
    with col3:
        if q["id"] in test["marked"]:
            if st.button("✅ Unmark", use_container_width=True):
                test["marked"].remove(q["id"])
                st.rerun()
        else:
            if st.button("🚩 Mark", use_container_width=True):
                test["marked"].add(q["id"])
                st.rerun()
    with col4:
        question_numbers = list(range(1, len(test["questions"]) + 1))
        selected_q = st.selectbox("Jump to", question_numbers, index=test["index"], key=f"jump_{test['index']}", label_visibility="collapsed")
        if selected_q - 1 != test["index"]:
            save_current_answer(test, q)
            test["index"] = selected_q - 1
            st.rerun()
    if test["mode"] == "Reading" and choice:
        st.divider()
        user_choice = choice
        correct_answer = q["answer"]
        explanation = q.get("explanation", "No explanation provided.")
        user_letter = None
        for k, v in q["options_map"].items():
            if v == user_choice:
                user_letter = k
                break
        if user_letter == correct_answer:
            st.success(f"**Correct!** ({correct_answer})")
        else:
            st.error(f"**Incorrect.** You chose {user_letter}, correct is {correct_answer}")
        st.info(f"**Explanation:** {explanation}")
    if test["mode"] == "Test" and not test.get("is_review"):
        time.sleep(1)
        st.rerun()
    st.stop()

if st.session_state.page == "test_review":
    if st.session_state.test is None:
        st.error("No test to review. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
    test = st.session_state.test
    q = test["questions"][test["index"]]
    col_head1, col_head2, col_head3 = st.columns([2, 3, 1])
    with col_head1:
        st.write(f"**Review Mode**")
    with col_head2:
        st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
    with col_head3:
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    st.divider()
    st.markdown(f"**{q['question']}**")
    user_answer = test["answers"].get(q["id"])
    correct_answer = q["answer"]
    for letter, option_text in q["options_map"].items():
        if option_text:
            col_option1, col_option2 = st.columns([1, 20])
            with col_option1:
                if letter == correct_answer:
                    st.success(f"**{letter}**")
                elif letter == user_answer:
                    st.error(f"**{letter}**")
                else:
                    st.write(f"**{letter}**")
            with col_option2:
                if letter == correct_answer:
                    st.success(option_text)
                elif letter == user_answer:
                    st.error(option_text)
                else:
                    st.write(option_text)
    st.divider()
    st.subheader("Explanation")
    explanation = q.get("explanation", "No explanation provided.")
    st.info(explanation)
    col_nav1, col_nav2, col_nav3 = st.columns(3)
    with col_nav1:
        if st.button("⬅ Previous", use_container_width=True, disabled=test["index"] == 0):
            test["index"] -= 1
            st.rerun()
    with col_nav2:
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    with col_nav3:
        next_disabled = test["index"] == len(test["questions"]) - 1
        if st.button("Next ➡", use_container_width=True, disabled=next_disabled):
            test["index"] += 1
            st.rerun()
    st.stop()

if st.session_state.page == "review":
    if st.session_state.test is None:
        st.error("No test to review. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
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
            if qid in prog["incorrect"]:
                prog["incorrect"].remove(qid)
        else:
            prog["incorrect"].add(qid)
            if qid in prog["correct"]:
                prog["correct"].remove(qid)
    prog["marked"].update(test["marked"])
    total = len(test["questions"])
    score_percent = (correct / total * 100) if total > 0 else 0
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Score", f"{correct}/{total}")
    with col2:
        st.metric("Percentage", f"{score_percent:.1f}%")
    with col3:
        if test["mode"] == "Test" and "start" in test:
            elapsed = int(time.time() - test["start"])
            st.metric("Time Taken", format_time(elapsed))
        else:
            if score_percent >= 70:
                st.success("🎉 Excellent!")
            elif score_percent >= 60:
                st.info("👍 Good")
            else:
                st.warning("📚 Needs Improvement")
    fig = go.Figure(data=[go.Pie(labels=['Correct', 'Incorrect'], values=[correct, total - correct], hole=0.3, marker_colors=['green', 'red'])])
    fig.update_layout(title_text="Test Performance")
    st.plotly_chart(fig, use_container_width=True)
    save_user_progress(st.session_state.user, prog)
    save_test_session(st.session_state.user, test, completed=True)
    st.subheader("Question Breakdown")
    for i, q in enumerate(test["questions"]):
        with st.expander(f"Question {i + 1}: {'✅' if test['answers'].get(q['id']) == q['answer'] else '❌'}"):
            st.write(f"**Question:** {q['question'][:100]}...")
            user_answer = test["answers"].get(q["id"])
            st.write(f"**Your answer:** {user_answer if user_answer else 'Not answered'}")
            st.write(f"**Correct answer:** {q['answer']}")
            st.write(f"**Explanation:** {q.get('explanation', 'No explanation provided.')}")
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    with col_btn1:
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    with col_btn2:
        if st.button("📊 Analytics", use_container_width=True):
            st.session_state.page = "previous_menu"
            st.rerun()
    with col_btn3:
        if st.button("🔍 Review Test", use_container_width=True):
            test["is_review"] = True
            test["index"] = 0
            st.session_state.page = "test_review"
            st.rerun()
    st.stop()