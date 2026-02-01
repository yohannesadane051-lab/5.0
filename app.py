import streamlit as st
import json, os, random, time, hashlib, uuid
from datetime import datetime
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
        rows = tests_ws.get_all_records()
        user_tests = []
        for r in rows:
            if r.get("username") == username:
                # Parse additional data stored in JSON format
                test_data = json.loads(r.get("test_data", "{}") or "{}")
                user_tests.append({
                    "test_id": r.get("test_id"),
                    "created": r.get("created"),
                    "mode": r.get("mode"),
                    "total_questions": r.get("total_questions", 0),
                    "score": r.get("score", 0),
                    "system": r.get("system", "All"),
                    "answers": test_data.get("answers", {}),
                    "questions": test_data.get("questions", []),
                    "index": test_data.get("index", 0),
                    "marked": set(test_data.get("marked", [])),
                    "completed": r.get("completed", False)
                })
        return sorted(user_tests, key=lambda x: x["created"], reverse=True)
    except Exception as e:
        st.error(f"Error getting user tests: {str(e)}")
        return []

def save_test_session(username, test, completed=True):
    try:
        # Get system info
        systems_in_test = set(q["system"] for q in test["questions"])
        system_str = ", ".join(sorted(systems_in_test)) if len(systems_in_test) <= 3 else "Multiple"
        
        # Calculate score
        score = 0
        for q in test["questions"]:
            if test["answers"].get(q["id"]) == q["answer"]:
                score += 1
        
        # Prepare test data for storage
        test_data = {
            "answers": test["answers"],
            "questions": test["questions"],
            "index": test["index"],
            "marked": list(test["marked"])
        }
        
        tests_ws.append_row([
            username,
            test["id"],
            datetime.now().isoformat(),
            test["mode"],
            len(test["questions"]),
            score,
            system_str,
            json.dumps(test_data),
            completed
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
    
    # Check for last test
    user_tests = get_user_tests(st.session_state.user)
    last_incomplete_test = None
    for test in user_tests:
        if not test.get("completed", False):
            last_incomplete_test = test
            break
    
    st.title("🏠 Home")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🧪 Create New Test", use_container_width=True):
            navigate_to("create")
    
    with col2:
        if st.button("📚 Previous Tests & Analytics", use_container_width=True):
            navigate_to("previous_menu")
    
    # Display last test option if available
    if last_incomplete_test:
        st.divider()
        st.subheader("Continue Last Session")
        st.write(f"**Mode:** {last_incomplete_test['mode']}")
        st.write(f"**Progress:** Question {last_incomplete_test['index'] + 1}/{last_incomplete_test['total_questions']}")
        if st.button("➡️ Continue Last Test"):
            # Restore test session
            st.session_state.test = {
                "id": last_incomplete_test["test_id"],
                "questions": last_incomplete_test["questions"],
                "answers": last_incomplete_test["answers"],
                "marked": last_incomplete_test["marked"],
                "index": last_incomplete_test["index"],
                "mode": last_incomplete_test["mode"],
                "start": time.time()
            }
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
        user_tests = get_user_tests(st.session_state.user)
        
        if not user_tests:
            st.info("No previous tests found.")
        else:
            # Filter out incomplete tests for this view
            completed_tests = [t for t in user_tests if t.get("completed", True)]
            
            if not completed_tests:
                st.info("No completed tests found.")
            else:
                # Create a clean dataframe for display
                test_data = []
                for test in completed_tests:
                    try:
                        created_date = datetime.fromisoformat(test["created"]).strftime("%Y-%m-%d %H:%M")
                    except:
                        created_date = test["created"]
                    
                    test_data.append({
                        "Created": created_date,
                        "Mode": test["mode"],
                        "Questions": test["total_questions"],
                        "Score": f"{test['score']}/{test['total_questions']}",
                        "System": test.get("system", "All"),
                        "Test ID": test["test_id"]
                    })
                
                df = pd.DataFrame(test_data)
                
                # Display table with selection
                for idx, row in df.iterrows():
                    with st.expander(f"Test {idx + 1}: {row['Created']} - {row['Mode']} Mode"):
                        st.write(f"**Date:** {row['Created']}")
                        st.write(f"**Mode:** {row['Mode']}")
                        st.write(f"**Questions:** {row['Questions']}")
                        st.write(f"**Score:** {row['Score']}")
                        st.write(f"**System:** {row['System']}")
                        
                        if st.button(f"Review Test {idx + 1}", key=f"review_{idx}"):
                            # Find the full test data
                            test_to_review = completed_tests[idx]
                            st.session_state.test = {
                                "id": test_to_review["test_id"],
                                "questions": test_to_review["questions"],
                                "answers": test_to_review["answers"],
                                "marked": test_to_review["marked"],
                                "index": 0,  # Start from beginning for review
                                "mode": test_to_review["mode"],
                                "is_review": True  # Flag for review mode
                            }
                            st.session_state.page = "test_review"
                            st.rerun()
    
    with tab2:
        st.subheader("📊 Your Analytics")
        
        prog = get_user_progress(st.session_state.user)
        user_tests = get_user_tests(st.session_state.user)
        completed_tests = [t for t in user_tests if t.get("completed", True)]
        
        # Basic stats
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
        
        # Pie chart for question status
        if used_questions > 0:
            fig1 = go.Figure(data=[go.Pie(
                labels=['Correct', 'Incorrect'],
                values=[correct_questions, incorrect_questions],
                hole=0.3
            )])
            fig1.update_layout(title_text="Performance on Used Questions")
            st.plotly_chart(fig1, use_container_width=True)
        
        # Test history performance
        if completed_tests:
            test_dates = []
            test_scores = []
            
            for test in completed_tests[-10:]:  # Last 10 tests
                try:
                    date = datetime.fromisoformat(test["created"]).strftime("%m-%d")
                    test_dates.append(date)
                    score_pct = (test["score"] / test["total_questions"]) * 100
                    test_scores.append(score_pct)
                except:
                    continue
            
            if test_dates and test_scores:
                fig2 = go.Figure(data=[go.Scatter(
                    x=test_dates,
                    y=test_scores,
                    mode='lines+markers',
                    name='Score %'
                )])
                fig2.update_layout(
                    title="Recent Test Performance",
                    xaxis_title="Test Date",
                    yaxis_title="Score %",
                    yaxis_range=[0, 100]
                )
                st.plotly_chart(fig2, use_container_width=True)
    
    with tab3:
        st.subheader("▶️ Continue Last Test")
        
        user_tests = get_user_tests(st.session_state.user)
        incomplete_tests = [t for t in user_tests if not t.get("completed", False)]
        
        if incomplete_tests:
            last_test = incomplete_tests[0]  # Most recent incomplete
            st.write(f"**Test Mode:** {last_test['mode']}")
            st.write(f"**Progress:** Question {last_test['index'] + 1}/{last_test['total_questions']}")
            st.write(f"**Started:** {last_test['created']}")
            
            if st.button("Continue from where you left off"):
                st.session_state.test = {
                    "id": last_test["test_id"],
                    "questions": last_test["questions"],
                    "answers": last_test["answers"],
                    "marked": last_test["marked"],
                    "index": last_test["index"],
                    "mode": last_test["mode"],
                    "start": time.time()
                }
                st.session_state.page = "test"
                st.rerun()
            
            if st.button("Restart this test from beginning"):
                st.session_state.test = {
                    "id": last_test["test_id"],
                    "questions": last_test["questions"],
                    "answers": {},
                    "marked": set(),
                    "index": 0,
                    "mode": last_test["mode"],
                    "start": time.time()
                }
                # Delete the incomplete test record
                try:
                    cell = tests_ws.find(last_test["test_id"], in_column=2)
                    tests_ws.delete_rows(cell.row)
                except:
                    pass
                st.session_state.page = "test"
                st.rerun()
        else:
            st.info("No incomplete tests found.")
    
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
                    "start": time.time(),
                    "is_review": False
                }
                # Save initial test session
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
    
    # Header with home button
    col_head1, col_head2, col_head3 = st.columns([2, 3, 1])
    with col_head1:
        st.write(f"**Mode:** {test['mode']}")
    with col_head2:
        st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
    with col_head3:
        if st.button("🏠 End & Save", type="secondary", use_container_width=True):
            # Save current progress
            save_current_answer(test, q)
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
        marker_colors=['#2ecc71', '#e74c3c']
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