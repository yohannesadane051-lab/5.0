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
        "tests": sh.worksheet("tests"),
        "analytics": sh.worksheet("analytics")
    }

# Initialize sheets connection
try:
    sheets = get_sheets_connection()
    users_ws = sheets["users"]
    progress_ws = sheets["progress"]
    tests_ws = sheets["tests"]
    analytics_ws = sheets["analytics"]
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

def update_analytics(username):
    """Update analytics sheet with current user stats"""
    try:
        prog = get_user_progress(username)
        total_questions = len(QUESTIONS)
        used_questions = len(prog["used"])
        unused_questions = total_questions - used_questions
        correct_questions = len(prog["correct"])
        incorrect_questions = len(prog["incorrect"])
        
        # Check if user exists in analytics sheet
        try:
            cell = analytics_ws.find(username)
            row = cell.row
            analytics_ws.update(
                f"B{row}:E{row}",
                [[
                    total_questions,
                    unused_questions,
                    correct_questions,
                    incorrect_questions
                ]]
            )
        except:
            # User not found, create new entry
            analytics_ws.append_row([
                username,
                total_questions,
                unused_questions,
                correct_questions,
                incorrect_questions
            ])
    except Exception as e:
        st.error(f"Error updating analytics: {str(e)}")

def get_user_tests(username):
    try:
        rows = tests_ws.get_all_records()
        user_tests = []
        for r in rows:
            if r.get("username") == username:
                # Parse test data
                state_json = r.get("state_json", "{}")
                try:
                    if state_json and state_json != "{}":
                        test_data = json.loads(state_json)
                    else:
                        test_data = {}
                except:
                    test_data = {}
                
                # Get current index (for incomplete tests)
                current_index = r.get("current_index", 0)
                try:
                    current_index = int(current_index)
                except:
                    current_index = 0
                
                # Parse creation date
                created_at = r.get("created_at", "")
                if created_at:
                    try:
                        # Try to parse ISO format
                        if "T" in created_at:
                            created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        else:
                            # Try other formats
                            created_date = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        created_str = created_date.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        created_str = created_at
                else:
                    created_str = ""
                
                user_tests.append({
                    "test_id": r.get("test_id", str(uuid.uuid4())),
                    "created": created_str,
                    "mode": r.get("mode", "Reading"),
                    "num_q": int(r.get("num_q", 0)),
                    "systems": r.get("systems", "All"),
                    "current_index": current_index,
                    "state_json": test_data,
                    "completed": r.get("completed", "false").lower() == "true"
                })
        
        # Sort by creation date (newest first)
        return sorted(user_tests, 
                     key=lambda x: x["created"] if x["created"] else "1970-01-01", 
                     reverse=True)
    except Exception as e:
        st.error(f"Error getting user tests: {str(e)}")
        return []

def save_test_session(username, test, completed=False):
    try:
        # Get system info - make sure we're getting it from the actual questions
        systems_in_test = set()
        for q in test["questions"]:
            if "system" in q:
                systems_in_test.add(q["system"])
        
        if len(systems_in_test) == 0:
            system_str = "All"
        elif len(systems_in_test) <= 3:
            system_str = ", ".join(sorted(systems_in_test))
        else:
            system_str = "Multiple"
        
        # Calculate score
        score = 0
        for q in test["questions"]:
            if test["answers"].get(q["id"]) == q["answer"]:
                score += 1
        
        # Prepare test data for storage
        test_data = {
            "answers": test["answers"],
            "questions": [
                {
                    "id": q["id"],
                    "question": q["question"][:500] if len(q["question"]) > 500 else q["question"],
                    "answer": q["answer"],
                    "explanation": q.get("explanation", "")[:500] if q.get("explanation") else "",
                    "system": q.get("system", "Unknown")
                }
                for q in test["questions"]
            ],
            "index": test["index"],
            "marked": list(test["marked"]),
            "mode": test["mode"],
            "start_time": test.get("start_time", time.time()),
            "total_time": test.get("total_time", 0)
        }
        
        # Check if test already exists
        try:
            # Try to find existing test
            cell_list = tests_ws.findall(test["id"])
            if cell_list:
                # Update existing test
                cell = cell_list[0]
                row = cell.row
                
                # Prepare update data
                update_data = [
                    username,  # username
                    test["id"],  # test_id
                    datetime.now().isoformat(),  # created_at
                    test["mode"],  # mode
                    len(test["questions"]),  # num_q
                    system_str,  # systems
                    test["index"],  # current_index
                    json.dumps(test_data),  # state_json
                    str(completed).lower(),  # completed
                    score,  # score
                    test.get("total_time", 0)  # total_time
                ]
                
                # Update the entire row
                tests_ws.update(f"A{row}:K{row}", [update_data])
            else:
                # Create new test entry
                tests_ws.append_row([
                    username,
                    test["id"],
                    datetime.now().isoformat(),
                    test["mode"],
                    len(test["questions"]),
                    system_str,
                    test["index"],
                    json.dumps(test_data),
                    str(completed).lower(),
                    score,
                    test.get("total_time", 0)
                ])
        except Exception as e:
            # If update fails, append as new
            tests_ws.append_row([
                username,
                test["id"],
                datetime.now().isoformat(),
                test["mode"],
                len(test["questions"]),
                system_str,
                test["index"],
                json.dumps(test_data),
                str(completed).lower(),
                score,
                test.get("total_time", 0)
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

def format_time(seconds):
    """Format seconds into MM:SS or HH:MM:SS"""
    if seconds < 3600:
        return time.strftime("%M:%S", time.gmtime(seconds))
    else:
        return time.strftime("%H:%M:%S", time.gmtime(seconds))

# ================= SESSION STATE INITIALIZATION =================
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
if "test_start_time" not in st.session_state:
    st.session_state.test_start_time = None
if "test_elapsed_time" not in st.session_state:
    st.session_state.test_elapsed_time = 0

def navigate_to(page):
    st.session_state.navigation_history.append(st.session_state.page)
    st.session_state.page = page
    st.rerun()

def go_back():
    if st.session_state.navigation_history:
        st.session_state.page = st.session_state.navigation_history.pop()
        st.rerun()
    else:
        st.session_state.page = "home"
        st.rerun()

# ================= AUTH =================
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
        
        # Initialize analytics
        update_analytics(username)
        
        return True
    except Exception as e:
        st.error(f"Signup error: {str(e)}")
        return False

# ================= LOGIN PAGE =================
if st.session_state.page == "login":
    st.title("🔐 USMLE Step 3 QBank")
    
    # Check if we have a saved user from interrupted session
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

# ================= HOME PAGE =================
if st.session_state.page == "home":
    st.sidebar.title(f"👤 {st.session_state.user}")
    
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.session_state.page = "login"
        st.rerun()
    
    # Check for last incomplete test
    user_tests = get_user_tests(st.session_state.user)
    incomplete_tests = [t for t in user_tests if not t["completed"]]
    last_incomplete_test = incomplete_tests[0] if incomplete_tests else None
    
    st.title("🏠 Home")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🧪 Create New Test", use_container_width=True):
            navigate_to("create")
    
    with col2:
        if st.button("📚 Previous Tests & Analytics", use_container_width=True):
            navigate_to("previous_menu")
    
    # Display last incomplete test option if available
    if last_incomplete_test:
        st.divider()
        st.subheader("Continue Last Session")
        
        # Format date for display
        try:
            created_date = datetime.strptime(last_incomplete_test["created"], "%Y-%m-%d %H:%M:%S")
            display_date = created_date.strftime("%Y-%m-%d %H:%M")
        except:
            display_date = last_incomplete_test.get("created", "Unknown date")
        
        st.write(f"**Mode:** {last_incomplete_test['mode']}")
        st.write(f"**Date:** {display_date}")
        st.write(f"**Progress:** Question {last_incomplete_test['current_index'] + 1}/{last_incomplete_test['num_q']}")
        st.write(f"**System:** {last_incomplete_test['systems']}")
        
        if st.button("➡️ Continue Last Test", key="continue_last_home", use_container_width=True):
            # Restore test from saved data
            test_data = last_incomplete_test["state_json"]
            
            # Restore questions
            restored_questions = []
            for q_data in test_data.get("questions", []):
                # Search for original question
                found = False
                for original_q in QUESTIONS:
                    if original_q["id"] == q_data.get("id"):
                        restored_questions.append(original_q)
                        found = True
                        break
                
                if not found:
                    # Create question from stored data
                    restored_questions.append({
                        "id": q_data.get("id", ""),
                        "system": q_data.get("system", "Unknown"),
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
                    "answers": test_data.get("answers", {}),
                    "marked": set(test_data.get("marked", [])),
                    "index": test_data.get("index", 0),
                    "mode": test_data.get("mode", last_incomplete_test["mode"]),
                    "start_time": test_data.get("start_time", time.time()),
                    "is_review": False,
                    "total_time": test_data.get("total_time", 0)
                }
                st.session_state.test_start_time = time.time()
                st.session_state.page = "test"
                st.rerun()
    
    st.stop()

# ================= PREVIOUS TESTS MENU =================
if st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests & Analytics")
    
    # Back button
    if st.button("← Back"):
        go_back()
    
    tab1, tab2, tab3 = st.tabs(["📋 Previous Tests", "📊 Analytics", "▶️ Last Test"])
    
    with tab1:
    st.subheader("Your Test History")
    user_tests = get_user_tests(st.session_state.user)
    
    if not user_tests:
        st.info("No tests found yet. Create your first test!")
    else:
        # Group tests by completion status
        completed_tests = [t for t in user_tests if t["completed"]]
        incomplete_tests = [t for t in user_tests if not t["completed"]]
        
        # Show incomplete tests first
        if incomplete_tests:
            st.write(f"**Incomplete Tests ({len(incomplete_tests)})**")
            for i, test in enumerate(incomplete_tests):
                # Format date
                try:
                    created_date = datetime.strptime(test["created"], "%Y-%m-%d %H:%M:%S")
                    display_date = created_date.strftime("%Y-%m-%d %H:%M")
                except:
                    display_date = test.get("created", "Unknown date")
                
                with st.expander(f"⚠️ Incomplete Test {i+1}: {test['mode']} Mode - {test['num_q']} questions", expanded=(i==0)):
                    st.write(f"**Date:** {display_date}")
                    st.write(f"**Mode:** {test['mode']}")
                    st.write(f"**Progress:** Question {test['current_index'] + 1}/{test['num_q']}")
                    st.write(f"**System:** {test['systems']}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        # Use a unique key that includes the index and test_id
                        unique_key = f"continue_{i}_{test['test_id'][:8]}_{test['created'][:10]}"
                        if st.button(f"Continue", key=unique_key):
                            # Restore test
                            test_data = test["state_json"]
                            
                            restored_questions = []
                            for q_data in test_data.get("questions", []):
                                # Find in QUESTIONS
                                found = False
                                for original_q in QUESTIONS:
                                    if original_q["id"] == q_data.get("id"):
                                        restored_questions.append(original_q)
                                        found = True
                                        break
                                
                                if not found:
                                    restored_questions.append({
                                        "id": q_data.get("id", ""),
                                        "system": q_data.get("system", "Unknown"),
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
                                    "answers": test_data.get("answers", {}),
                                    "marked": set(test_data.get("marked", [])),
                                    "index": test_data.get("index", 0),
                                    "mode": test_data.get("mode", test["mode"]),
                                    "start_time": test_data.get("start_time", time.time()),
                                    "is_review": False,
                                    "total_time": test_data.get("total_time", 0)
                                }
                                st.session_state.test_start_time = time.time()
                                st.session_state.page = "test"
                                st.rerun()
                    
                    with col2:
                        # Unique delete button key
                        delete_key = f"delete_{i}_{test['test_id'][:8]}_{test['created'][:10]}"
                        if st.button(f"Delete", key=delete_key):
                            # Mark as completed (soft delete)
                            try:
                                cell_list = tests_ws.findall(test["test_id"])
                                if cell_list:
                                    cell = cell_list[0]
                                    row = cell.row
                                    tests_ws.update_cell(row, 9, "true")  # Mark as completed
                                    st.success("Test deleted!")
                                    time.sleep(1)
                                    st.rerun()
                            except:
                                st.error("Could not delete test")
            
            st.divider()
        
        # Show completed tests
        if completed_tests:
            st.write(f"**Completed Tests ({len(completed_tests)})**")
            for i, test in enumerate(completed_tests):
                # Format date
                try:
                    created_date = datetime.strptime(test["created"], "%Y-%m-%d %H:%M:%S")
                    display_date = created_date.strftime("%Y-%m-%d %H:%M")
                except:
                    display_date = test.get("created", "Unknown date")
                
                # Calculate score from test data
                test_data = test["state_json"]
                score = 0
                total = len(test_data.get("questions", []))
                if total > 0:
                    for q_data in test_data.get("questions", []):
                        qid = q_data.get("id")
                        user_answer = test_data.get("answers", {}).get(qid)
                        correct_answer = q_data.get("answer")
                        if user_answer == correct_answer:
                            score += 1
                
                with st.expander(f"Test {i+1}: {test['mode']} Mode - Score: {score}/{total}", expanded=(i==0 and not incomplete_tests)):
                    st.write(f"**Date:** {display_date}")
                    st.write(f"**Mode:** {test['mode']}")
                    st.write(f"**Questions:** {test['num_q']}")
                    st.write(f"**Score:** {score}/{total}")
                    st.write(f"**System:** {test['systems']}")
                    
                    # Unique review button key
                    review_key = f"review_{i}_{test['test_id'][:8]}_{test['created'][:10]}"
                    if st.button(f"Review This Test", key=review_key):
                        # Restore for review
                        restored_questions = []
                        for q_data in test_data.get("questions", []):
                            # Find in QUESTIONS
                            found = False
                            for original_q in QUESTIONS:
                                if original_q["id"] == q_data.get("id"):
                                    restored_questions.append(original_q)
                                    found = True
                                    break
                            
                            if not found:
                                restored_questions.append({
                                    "id": q_data.get("id", ""),
                                    "system": q_data.get("system", "Unknown"),
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
                                "answers": test_data.get("answers", {}),
                                "marked": set(test_data.get("marked", [])),
                                "index": 0,
                                "mode": test["mode"],
                                "is_review": True,
                                "total_time": test_data.get("total_time", 0)
                            }
                            st.session_state.page = "test_review"
                            st.rerun()
        elif not incomplete_tests:
            st.info("No tests found. Create your first test!")
    
    with tab2:
        st.subheader("📊 Your Analytics")
        
        prog = get_user_progress(st.session_state.user)
        user_tests = get_user_tests(st.session_state.user)
        
        # Update analytics sheet
        update_analytics(st.session_state.user)
        
        # Get analytics from sheet
        try:
            rows = analytics_ws.get_all_records()
            user_analytics = None
            for r in rows:
                if r.get("username") == st.session_state.user:
                    user_analytics = r
                    break
            
            if user_analytics:
                total_questions = user_analytics.get("total", 0)
                unused_questions = user_analytics.get("unused", 0)
                correct_questions = user_analytics.get("correct", 0)
                incorrect_questions = user_analytics.get("incorrect", 0)
            else:
                # Calculate from progress
                total_questions = len(QUESTIONS)
                used_questions = len(prog["used"])
                unused_questions = total_questions - used_questions
                correct_questions = len(prog["correct"])
                incorrect_questions = len(prog["incorrect"])
        except:
            # Fallback to progress calculation
            total_questions = len(QUESTIONS)
            used_questions = len(prog["used"])
            unused_questions = total_questions - used_questions
            correct_questions = len(prog["correct"])
            incorrect_questions = len(prog["incorrect"])
        
        # Basic stats
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Questions", total_questions)
        with col2:
            st.metric("Unused Questions", unused_questions)
        with col3:
            st.metric("Correct", correct_questions)
        with col4:
            st.metric("Incorrect", incorrect_questions)
        
        # Progress bar for question usage
        if total_questions > 0:
            usage_percent = ((total_questions - unused_questions) / total_questions) * 100
            st.progress(usage_percent / 100)
            st.write(f"**Question Usage:** {total_questions - unused_questions}/{total_questions} ({usage_percent:.1f}%)")
        
        # Pie chart for performance
        answered_questions = correct_questions + incorrect_questions
        if answered_questions > 0:
            fig = go.Figure(data=[go.Pie(
                labels=['Correct', 'Incorrect'],
                values=[correct_questions, incorrect_questions],
                hole=0.3,
                marker_colors=['green', 'red']
            )])
            fig.update_layout(
                title_text="Question Performance",
                showlegend=True
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Additional analytics
        st.subheader("Additional Statistics")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Accuracy rate
            if answered_questions > 0:
                accuracy = (correct_questions / answered_questions) * 100
                st.metric("Accuracy Rate", f"{accuracy:.1f}%")
            else:
                st.metric("Accuracy Rate", "0%")
            
            # Average test score
            completed_tests = [t for t in user_tests if t["completed"]]
            if completed_tests:
                total_score = 0
                total_questions_in_tests = 0
                for test in completed_tests:
                    test_data = test["state_json"]
                    total = len(test_data.get("questions", []))
                    if total > 0:
                        score = 0
                        for q_data in test_data.get("questions", []):
                            qid = q_data.get("id")
                            user_answer = test_data.get("answers", {}).get(qid)
                            correct_answer = q_data.get("answer")
                            if user_answer == correct_answer:
                                score += 1
                        total_score += score
                        total_questions_in_tests += total
                
                if total_questions_in_tests > 0:
                    avg_score = (total_score / total_questions_in_tests) * 100
                    st.metric("Average Test Score", f"{avg_score:.1f}%")
        
        with col2:
            # Number of tests
            total_tests = len(user_tests)
            completed_tests_count = len([t for t in user_tests if t["completed"]])
            st.metric("Total Tests", total_tests)
            st.metric("Completed Tests", completed_tests_count)
    
    with tab3:
        st.subheader("▶️ Continue Last Test")
        
        user_tests = get_user_tests(st.session_state.user)
        incomplete_tests = [t for t in user_tests if not t["completed"]]
        
        if incomplete_tests:
            test = incomplete_tests[0]  # Most recent incomplete
            
            # Format date
            try:
                created_date = datetime.strptime(test["created"], "%Y-%m-%d %H:%M:%S")
                display_date = created_date.strftime("%Y-%m-%d %H:%M")
            except:
                display_date = test.get("created", "Unknown date")
            
            st.write(f"**Last Incomplete Test**")
            st.write(f"**Date:** {display_date}")
            st.write(f"**Mode:** {test['mode']}")
            st.write(f"**Progress:** Question {test['current_index'] + 1}/{test['num_q']}")
            st.write(f"**System:** {test['systems']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Continue Test", use_container_width=True):
                    # Restore test
                    test_data = test["state_json"]
                    
                    restored_questions = []
                    for q_data in test_data.get("questions", []):
                        # Find in QUESTIONS
                        found = False
                        for original_q in QUESTIONS:
                            if original_q["id"] == q_data.get("id"):
                                restored_questions.append(original_q)
                                found = True
                                break
                        
                        if not found:
                            restored_questions.append({
                                "id": q_data.get("id", ""),
                                "system": q_data.get("system", "Unknown"),
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
                            "answers": test_data.get("answers", {}),
                            "marked": set(test_data.get("marked", [])),
                            "index": test_data.get("index", 0),
                            "mode": test_data.get("mode", test["mode"]),
                            "start_time": test_data.get("start_time", time.time()),
                            "is_review": False,
                            "total_time": test_data.get("total_time", 0)
                        }
                        st.session_state.test_start_time = time.time()
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

# ================= CREATE TEST PAGE =================
if st.session_state.page == "create":
    st.title("🧪 Create New Test")
    
    # Back button
    if st.button("← Back"):
        go_back()
    
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
                    "start_time": time.time(),
                    "is_review": False,
                    "total_time": 0
                }
                st.session_state.test_start_time = time.time()
                # Save as incomplete
                save_test_session(st.session_state.user, st.session_state.test, completed=False)
                st.session_state.page = "test"
                st.rerun()
    
    st.stop()

# ================= TEST PAGE =================
if st.session_state.page == "test":
    if st.session_state.test is None:
        st.error("No test session found. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
    
    test = st.session_state.test
    q = test["questions"][test["index"]]
    
    # Calculate timer values
    if st.session_state.test_start_time is None:
        st.session_state.test_start_time = time.time()
    
    elapsed_time = time.time() - st.session_state.test_start_time
    total_allowed_time = len(test["questions"]) * 90  # 90 seconds per question
    remaining_time = max(0, total_allowed_time - elapsed_time)
    
    # Update total time in test object
    test["total_time"] = elapsed_time
    
    # Header with timer and home button
    col_head1, col_head2, col_head3, col_head4 = st.columns([2, 3, 2, 1])
    with col_head1:
        st.write(f"**Mode:** {test['mode']}")
    with col_head2:
        st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
    with col_head3:
        # Timer display
        if test["mode"] == "Test":
            st.markdown(f"""
            <div style="background-color: #f0f2f6; padding: 10px; border-radius: 5px; text-align: center;">
                <div style="font-size: 14px; color: #666;">Time Used / Remaining</div>
                <div style="font-size: 20px; font-weight: bold; color: {'red' if remaining_time < 60 else 'green'}">
                    {format_time(elapsed_time)} / {format_time(remaining_time)}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.write(f"**Reading Mode**")
    with col_head4:
        if st.button("🏠 End & Save", type="secondary", use_container_width=True):
            # Save current progress
            save_current_answer(test, q)
            test["total_time"] = elapsed_time
            save_test_session(st.session_state.user, test, completed=False)
            st.session_state.page = "home"
            st.rerun()
    
    st.divider()
    
    # Question display
    st.markdown(f"**{q['question']}**")
    
    # Options
    radio_key = f"q_{q['id']}_answer_{test['index']}"
    
    # Get current answer if exists
    current_answer = None
    if q["id"] in test["answers"]:
        current_answer = q["options_map"][test["answers"][q["id"]]]
    
    choice = st.radio(
        "Select answer",
        q["options"],
        index=q["options"].index(current_answer) if current_answer in q["options"] else None,
        key=radio_key
    )
    
    # Update session state
    if choice:
        st.session_state.current_choice = choice
        # Auto-save answer
        save_current_answer(test, q)
    
    # Navigation buttons
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
                # End of test
                test["total_time"] = elapsed_time
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
        # Jump to question
        question_numbers = list(range(1, len(test["questions"]) + 1))
        selected_q = st.selectbox(
            "Jump to",
            question_numbers,
            index=test["index"],
            key=f"jump_{test['index']}",
            label_visibility="collapsed"
        )
        if selected_q - 1 != test["index"]:
            save_current_answer(test, q)
            test["index"] = selected_q - 1
            st.rerun()
    
    # ================= READING MODE ANSWER DISPLAY =================
    if test["mode"] == "Reading" and choice:
        st.divider()
        user_choice = choice
        correct_answer = q["answer"]
        explanation = q.get("explanation", "No explanation provided.")
        
        # Map user choice back to letter
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
    
    # Auto-save progress periodically (every 30 seconds)
    if time.time() - st.session_state.test_start_time > 30:
        save_current_answer(test, q)
        test["total_time"] = elapsed_time
        save_test_session(st.session_state.user, test, completed=False)
        st.session_state.test_start_time = time.time()  # Reset timer
    
    st.stop()

# ================= TEST REVIEW MODE =================
if st.session_state.page == "test_review":
    if st.session_state.test is None:
        st.error("No test to review. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
    
    test = st.session_state.test
    q = test["questions"][test["index"]]
    
    # Header
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
    
    # Question display
    st.markdown(f"**{q['question']}**")
    
    # Display all options with correct/incorrect highlighting
    user_answer = test["answers"].get(q["id"])
    correct_answer = q["answer"]
    
    for letter, option_text in q["options_map"].items():
        if option_text:  # Skip empty options
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
    
    # Explanation
    st.divider()
    st.subheader("Explanation")
    explanation = q.get("explanation", "No explanation provided.")
    st.info(explanation)
    
    # Show test time if available
    if test.get("total_time", 0) > 0:
        st.write(f"**Test Duration:** {format_time(test['total_time'])}")
    
    # Navigation
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

# ================= REVIEW/SCORE PAGE =================
if st.session_state.page == "review":
    if st.session_state.test is None:
        st.error("No test to review. Returning to home.")
        st.session_state.page = "home"
        st.rerun()
    
    st.title("📊 Test Results")
    
    test = st.session_state.test
    prog = get_user_progress(st.session_state.user)
    
    # Calculate score
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
    
    # Update analytics
    update_analytics(st.session_state.user)
    
    # Display test time
    if test.get("total_time", 0) > 0:
        st.write(f"**Test Duration:** {format_time(test['total_time'])}")
    
    # Display metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Score", f"{correct}/{total}")
    
    with col2:
        st.metric("Percentage", f"{score_percent:.1f}%")
    
    with col3:
        # Performance indicator
        if score_percent >= 70:
            st.success("🎉 Excellent!")
        elif score_percent >= 60:
            st.info("👍 Good")
        else:
            st.warning("📚 Needs Improvement")
    
    # Pie chart
    fig = go.Figure(data=[go.Pie(
        labels=['Correct', 'Incorrect'],
        values=[correct, total - correct],
        hole=0.3,
        marker_colors=['green', 'red']
    )])
    fig.update_layout(title_text="Test Performance")
    st.plotly_chart(fig, use_container_width=True)
    
    # Save progress and test results
    save_user_progress(st.session_state.user, prog)
    save_test_session(st.session_state.user, test, completed=True)
    
    # Question breakdown
    st.subheader("Question Breakdown")
    
    for i, q in enumerate(test["questions"]):
        with st.expander(f"Question {i + 1}: {'✅' if test['answers'].get(q['id']) == q['answer'] else '❌'}"):
            st.write(f"**Question:** {q['question'][:100]}...")
            user_answer = test["answers"].get(q["id"])
            st.write(f"**Your answer:** {user_answer if user_answer else 'Not answered'}")
            st.write(f"**Correct answer:** {q['answer']}")
            st.write(f"**Explanation:** {q.get('explanation', 'No explanation provided.')}")
    
    # Action buttons
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