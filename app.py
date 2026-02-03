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
[span_0](start_span)st.set_page_config(page_title="USMLE Step 3 QBank", layout="wide", initial_sidebar_state="collapsed")[span_0](end_span)

# ================= CACHED SHEETS CONNECTION =================
@st.cache_resource(ttl=300)  # Cache for 5 minutes to reduce API calls
def get_sheets_connection():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds = Credentials.from_service_account_info(
        [span_1](start_span)st.secrets["gcp_service_account"],[span_1](end_span)
        scopes=SCOPES
    [span_2](start_span))
    
    gc = gspread.authorize(creds)
    sh = gc.open(st.secrets["SHEET_NAME"])[span_2](end_span)
    
    return {
        "users": sh.worksheet("users"),
        "progress": sh.worksheet("progress"),
        "tests": sh.worksheet("tests")
    [span_3](start_span)}

# Initialize sheets connection
try:
    sheets = get_sheets_connection()
    users_ws = sheets["users"]
    progress_ws = sheets["progress"]
    tests_ws = sheets["tests"][span_3](end_span)
except Exception as e:
    [span_4](start_span)st.error(f"Error connecting to Google Sheets: {str(e)}")[span_4](end_span)
    [span_5](start_span)st.stop()[span_5](end_span)

# ================= HELPERS =================
def hash_pw(pw):
    [span_6](start_span)return hashlib.sha256(pw.encode()).hexdigest()[span_6](end_span)

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_all_questions():
    qs = []
    for f in os.listdir():
        if f.endswith(".json"):
            try:
                [span_7](start_span)with open(f, encoding="utf-8") as file:[span_7](end_span)
                    [span_8](start_span)data = json.load(file)[span_8](end_span)
                
                for q in data:
                    q["id"] = f"{q['system']}_{q['id']}"
                    [span_9](start_span)q["options_map"] = {[span_9](end_span)
                        "A": q["choice_a"],
                        "B": q["choice_b"],
                        "C": q["choice_c"],
                        [span_10](start_span)"D": q["choice_d"],[span_10](end_span)
                        [span_11](start_span)"E": q.get("choice_e")[span_11](end_span)
                    }
                    q["options"] = [v for v in q["options_map"].values() if v]
                    q["answer"] = q["correct_answer"]
                    [span_12](start_span)q["question"] = q["stem"][span_12](end_span)
                    [span_13](start_span)qs.append(q)[span_13](end_span)
            except Exception as e:
                st.error(f"Error loading {f}: {str(e)}")
                continue
    return qs

QUESTIONS = load_all_questions()
[span_14](start_span)SYSTEMS = sorted(set(q["system"] for q in QUESTIONS))[span_14](end_span)

def get_user_progress(username):
    try:
        [span_15](start_span)rows = progress_ws.get_all_records()[span_15](end_span)
        [span_16](start_span)for r in rows:[span_16](end_span)
            if r.get("username") == username:
                return {
                    "used": set(json.loads(r.get("used", "[]") or "[]")),
                    [span_17](start_span)"correct": set(json.loads(r.get("correct", "[]") or "[]")),[span_17](end_span)
                    [span_18](start_span)"incorrect": set(json.loads(r.get("incorrect", "[]") or "[]")),[span_18](end_span)
                    "marked": set(json.loads(r.get("marked", "[]") or "[]")),
                }
        # If user not found, create entry
        progress_ws.append_row([username, "[]", "[]", "[]", "[]"])
        return {"used": set(), "correct": set(), "incorrect": set(), "marked": set()}
    [span_19](start_span)except Exception as e:[span_19](end_span)
        st.error(f"Error getting user progress: {str(e)}")
        return {"used": set(), "correct": set(), "incorrect": set(), "marked": set()}

def save_user_progress(username, prog):
    try:
        cell = progress_ws.find(username)
        row = cell.row
        progress_ws.update(
            f"B{row}:E{row}",
            [span_20](start_span)[[[span_20](end_span)
                [span_21](start_span)json.dumps(list(prog["used"])),[span_21](end_span)
                json.dumps(list(prog["correct"])),
                json.dumps(list(prog["incorrect"])),
                json.dumps(list(prog["marked"]))
            ]]
        )
    except Exception as e:
        [span_22](start_span)st.error(f"Error saving progress: {str(e)}")[span_22](end_span)

def get_user_tests(username):
    try:
        [span_23](start_span)rows = tests_ws.get_all_records()[span_23](end_span)
        user_tests = []
        for r in rows:
            if r.get("username") == username:
                # Get test data - handle different formats
                test_data = {}
                [span_24](start_span)test_data_str = r.get("test_data", "{}")[span_24](end_span)
                
                [span_25](start_span)if test_data_str and test_data_str != "{}":[span_25](end_span)
                    try:
                        [span_26](start_span)if isinstance(test_data_str, str):[span_26](end_span)
                            [span_27](start_span)test_data = json.loads(test_data_str)[span_27](end_span)
                        else:
                            test_data = test_data_str
                    [span_28](start_span)except:[span_28](end_span)
                        [span_29](start_span)test_data = {}[span_29](end_span)
                
                # Determine if test is completed
                completed = True  # Default to True for backward compatibility
                
                # [span_30](start_span)Check if "completed" column exists and has value[span_30](end_span)
                if "completed" in r:
                    completed_val = r["completed"]
                    [span_31](start_span)if isinstance(completed_val, str):[span_31](end_span)
                        [span_32](start_span)completed = completed_val.lower() in ["true", "yes", "1", "completed"][span_32](end_span)
                    elif isinstance(completed_val, bool):
                        completed = completed_val
                    [span_33](start_span)elif isinstance(completed_val, (int, float)):[span_33](end_span)
                        [span_34](start_span)completed = bool(completed_val)[span_34](end_span)
                
                # Get score and total questions
                try:
                    [span_35](start_span)total_questions = int(r.get("total_questions", 0))[span_35](end_span)
                    [span_36](start_span)score = int(r.get("score", 0))[span_36](end_span)
                except:
                    total_questions = 0
                    score = 0
                
                [span_37](start_span)user_tests.append({[span_37](end_span)
                    [span_38](start_span)"test_id": r.get("test_id", ""),[span_38](end_span)
                    "created": r.get("created", ""),
                    "mode": r.get("mode", ""),
                    [span_39](start_span)"total_questions": total_questions,[span_39](end_span)
                    [span_40](start_span)"score": score,[span_40](end_span)
                    "system": r.get("system", "All"),
                    "answers": test_data.get("answers", {}),
                    "questions": test_data.get("questions", []),
                    [span_41](start_span)"index": test_data.get("index", 0),[span_41](end_span)
                    [span_42](start_span)"marked": set(test_data.get("marked", [])),[span_42](end_span)
                    "completed": completed
                })
        
        # Sort by creation date (most recent first)
        def get_sortable_date(test_obj):
            [span_43](start_span)created_str = test_obj.get("created", "")[span_43](end_span)
            # Try to parse as date object first
            if isinstance(created_str, (datetime, pd.Timestamp)):
                return created_str
            # Try to parse string
            [span_44](start_span)try:[span_44](end_span)
                # Remove any quotes if present
                [span_45](start_span)created_str = str(created_str).strip('"\'')[span_45](end_span)
                # Try ISO format first
                try:
                    return datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                [span_46](start_span)except:[span_46](end_span)
                    # [span_47](start_span)Try other common formats[span_47](end_span)
                    for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"]:
                        try:
                            [span_48](start_span)return datetime.strptime(created_str, fmt)[span_48](end_span)
                        [span_49](start_span)except:[span_49](end_span)
                            continue
            except:
                pass
            # [span_50](start_span)Return a very old date if parsing fails[span_50](end_span)
            [span_51](start_span)return datetime.min[span_51](end_span)
        
        return sorted(user_tests, key=get_sortable_date, reverse=True)
    except Exception as e:
        [span_52](start_span)st.error(f"Error getting user tests: {str(e)}")[span_52](end_span)
        return []

def save_test_session(username, test, completed=True):
    try:
        # Get system info
        systems_in_test = set(q["system"] for q in test["questions"])
        [span_53](start_span)system_str = ", ".join(sorted(systems_in_test)) if len(systems_in_test) <= 3 else "Multiple"[span_53](end_span)
        
        # Calculate score
        score = 0
        for q in test["questions"]:
            if test["answers"].get(q["id"]) == q["answer"]:
                score += 1
        
        # [span_54](start_span)Prepare test data for storage[span_54](end_span)
        test_data = {
            "answers": test["answers"],
            "questions": [
                {
                    "id": q["id"],
                    [span_55](start_span)"question": q["question"][:500] if len(q["question"]) > 500 else q["question"],[span_55](end_span)
                    "answer": q["answer"],
                    "explanation": q.get("explanation", "")[:500] if q.get("explanation") and len(q.get("explanation", "")) > 500 else q.get("explanation", "")
                }
                [span_56](start_span)for q in test["questions"][span_56](end_span)
            [span_57](start_span)],[span_57](end_span)
            "index": test["index"],
            "marked": list(test["marked"])
        }
        
        # Get current timestamp
        current_time = datetime.now()
        
        # Check if test already exists by searching for test_id
        [span_58](start_span)try:[span_58](end_span)
            # [span_59](start_span)Try to find existing test[span_59](end_span)
            cell_list = tests_ws.findall(test["id"])
            if cell_list:
                # Update existing test
                cell = cell_list[0]
                [span_60](start_span)row = cell.row[span_60](end_span)
                
                # [span_61](start_span)Update the row[span_61](end_span)
                tests_ws.update(f"C{row}:I{row}", [[
                    current_time.isoformat(),
                    [span_62](start_span)test["mode"],[span_62](end_span)
                    [span_63](start_span)len(test["questions"]),[span_63](end_span)
                    score,
                    system_str,
                    json.dumps(test_data),
                    [span_64](start_span)str(completed).lower()[span_64](end_span)
                [span_65](start_span)]])[span_65](end_span)
            else:
                # Create new test entry
                tests_ws.append_row([
                    username,
                    [span_66](start_span)test["id"],[span_66](end_span)
                    [span_67](start_span)current_time.isoformat(),[span_67](end_span)
                    test["mode"],
                    len(test["questions"]),
                    score,
                    [span_68](start_span)system_str,[span_68](end_span)
                    [span_69](start_span)json.dumps(test_data),[span_69](end_span)
                    str(completed).lower()
                ])
        except Exception as e:
            # If search fails, just append as new
            [span_70](start_span)tests_ws.append_row([[span_70](end_span)
                [span_71](start_span)username,[span_71](end_span)
                test["id"],
                current_time.isoformat(),
                test["mode"],
                len(test["questions"]),
                [span_72](start_span)score,[span_72](end_span)
                [span_73](start_span)system_str,[span_73](end_span)
                json.dumps(test_data),
                str(completed).lower()
            ])
        
        return True
    except Exception as e:
        [span_74](start_span)st.error(f"Error saving test session: {str(e)}")[span_74](end_span)
        return False

def save_current_answer(test, q):
    [span_75](start_span)if "current_choice" in st.session_state and st.session_state.current_choice:[span_75](end_span)
        for k, v in q["options_map"].items():
            if v == st.session_state.current_choice:
                test["answers"][q["id"]] = k
                break

# ================= TIMER FUNCTIONS =================
def calculate_total_test_time(num_questions):
    """Calculate total test time based on 90 seconds per question"""
    total_seconds = num_questions * 90
    return total_seconds

def format_time(seconds):
    [span_76](start_span)"""Format seconds to HH:MM:SS"""[span_76](end_span)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def update_timer(test):
    """Update timer in session state"""
    if test.get("mode") == "Test" and "start" in test:
        elapsed = int(time.time() - test["start"])
        total_time = calculate_total_test_time(len(test["questions"]))
        remaining = max(0, total_time - elapsed)
        
        # [span_77](start_span)Update timer state[span_77](end_span)
        st.session_state.timer_elapsed = elapsed
        st.session_state.timer_remaining = remaining
        
        # Check if time is up
        if remaining <= 0 and not test.get("is_review"):
            st.session_state.time_up = True
            return True
    return False

# ================= SESSION STATE INITIALIZATION =================
[span_78](start_span)if "page" not in st.session_state:[span_78](end_span)
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
# FIX: Add a flag to clear cached content
if "clear_cache_on_test" not in st.session_state:
    st.session_state.clear_cache_on_test = False

def navigate_to(page):
    [span_79](start_span)st.session_state.navigation_history.append(st.session_state.page)[span_79](end_span)
    st.session_state.page = page
    # FIX: Set flag to clear cache when navigating to test
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

# ================= AUTH =================
def login(username, pw):
    try:
        [span_80](start_span)for r in users_ws.get_all_records():[span_80](end_span)
            if r["username"] == username and r["password_hash"] == hash_pw(pw):
                return True
        return False
    except Exception as e:
        st.error(f"Login error: {str(e)}")
        return False

def signup(username, pw):
    try:
        [span_81](start_span)if any(r["username"] == username for r in users_ws.get_all_records()):[span_81](end_span)
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
    
    [span_82](start_span)if st.session_state.user:[span_82](end_span)
        if st.button("↩️ Return to Session"):
            st.session_state.page = "home"
            st.rerun()
    
    t1, t2 = st.tabs(["Login", "Sign Up"])
    
    with t1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            [span_83](start_span)if login(u, p):[span_83](end_span)
                st.session_state.user = u
                st.session_state.page = "home"
                st.session_state.navigation_history = []
                st.rerun()
            else:
                [span_84](start_span)st.error("Invalid credentials")[span_84](end_span)
    
    with t2:
        nu = st.text_input("New username")
        np = st.text_input("New password", type="password")
        if st.button("Create Account"):
            if signup(nu, np):
                [span_85](start_span)st.success("Account created. Please login.")[span_85](end_span)
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
    
    # [span_86](start_span)Check for last incomplete test[span_86](end_span)
    user_tests = get_user_tests(st.session_state.user)
    incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
    last_incomplete_test = incomplete_tests[0] if incomplete_tests else None
    
    st.title("🏠 Home")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🧪 Create New Test", use_container_width=True):
            navigate_to("create")
    
    with col2:
        [span_87](start_span)if st.button("📚 Previous Tests & Analytics", use_container_width=True):[span_87](end_span)
            navigate_to("previous_menu")
    
    # Display last incomplete test option if available
    if last_incomplete_test:
        st.divider()
        st.subheader("Continue Last Session")
        st.write(f"**Mode:** {last_incomplete_test['mode']}")
        st.write(f"**Progress:** Question {last_incomplete_test['index'] + 1}/{last_incomplete_test['total_questions']}")
        
        if st.button("➡️ Continue Last Test", key="continue_last_home"):
            [span_88](start_span)restored_questions = [][span_88](end_span)
            for q_data in last_incomplete_test["questions"]:
                found = False
                for original_q in QUESTIONS:
                    if original_q["id"] == q_data.get("id"):
                        [span_89](start_span)restored_questions.append(original_q)[span_89](end_span)
                        found = True
                        break
                
                if not found:
                    [span_90](start_span)restored_questions.append({[span_90](end_span)
                        "id": q_data.get("id", ""),
                        "system": "Unknown",
                        [span_91](start_span)"question": q_data.get("question", "Question not found"),[span_91](end_span)
                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                        "options": ["Option A", "Option B", "Option C", "Option D"],
                        [span_92](start_span)"answer": q_data.get("answer", "A"),[span_92](end_span)
                        "explanation": q_data.get("explanation", "")
                    })
            
            if restored_questions:
                st.session_state.test = {
                    "id": last_incomplete_test["test_id"],
                    [span_93](start_span)"questions": restored_questions,[span_93](end_span)
                    "answers": last_incomplete_test["answers"],
                    "marked": last_incomplete_test["marked"],
                    "index": last_incomplete_test["index"],
                    [span_94](start_span)"mode": last_incomplete_test["mode"],[span_94](end_span)
                    "start": time.time(),
                    "is_review": False
                }
                st.session_state.page = "test"
                st.rerun()
    
    [span_95](start_span)st.stop()[span_95](end_span)

# ================= PREVIOUS TESTS MENU =================
if st.session_state.page == "previous_menu":
    st.title("📚 Previous Tests & Analytics")
    
    if st.button("← Back"):
        go_back()
    
    tab1, tab2, tab3 = st.tabs(["📋 Previous Tests", "📊 Analytics", "▶️ Last Test"])
    
    with tab1:
        st.subheader("Your Test History")
        user_tests = get_user_tests(st.session_state.user)
        
        [span_96](start_span)if not user_tests:[span_96](end_span)
            [span_97](start_span)st.info("No tests found yet. Create your first test!")[span_97](end_span)
        else:
            completed_tests = [t for t in user_tests if t.get("completed", True)]
            incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
            
            if incomplete_tests:
                st.write(f"**Incomplete Tests ({len(incomplete_tests)})**")
                [span_98](start_span)for i, test in enumerate(incomplete_tests):[span_98](end_span)
                    with st.expander(f"⚠️ Incomplete Test {i+1}: {test.get('mode', 'Unknown')} Mode", expanded=(i==0)):
                        # [span_99](start_span)FIXED: Improved date formatting with proper try-except structure[span_99](end_span)
                        formatted_date = "Unknown date"
                        created_str = test.get("created", "")
                        
                        if created_str:
                            [span_100](start_span)try:[span_100](end_span)
                                created_str = str(created_str).strip()
                                
                                # [span_101](start_span)Try to parse the date string[span_101](end_span)
                                created_date = None
                                
                                # [span_102](start_span)Try ISO format first (most common)[span_102](end_span)
                                try:
                                    # [span_103](start_span)Handle ISO format with or without timezone[span_103](end_span)
                                    if 'T' in created_str:
                                        # [span_104](start_span)ISO format with T separator[span_104](end_span)
                                        if created_str.endswith('Z'):
                                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                        [span_105](start_span)else:[span_105](end_span)
                                            # Check if timezone info is missing
                                            [span_106](start_span)if '+' in created_str or '-' in created_str[-6:]:[span_106](end_span)
                                                created_date = datetime.fromisoformat(created_str)
                                            else:
                                                # [span_107](start_span)No timezone, add it[span_107](end_span)
                                                [span_108](start_span)created_date = datetime.fromisoformat(created_str + '+00:00')[span_108](end_span)
                                    else:
                                        # [span_109](start_span)Not ISO format, try other formats[span_109](end_span)
                                        date_formats = [
                                            [span_110](start_span)"%Y-%m-%d %H:%M:%S.%f",[span_110](end_span)
                                            "%Y-%m-%d %H:%M:%S",
                                            [span_111](start_span)"%m/%d/%Y %H:%M:%S",[span_111](end_span)
                                            "%d/%m/%Y %H:%M:%S",
                                            "%Y-%m-%d",
                                            [span_112](start_span)"%m/%d/%Y",[span_112](end_span)
                                            "%d/%m/%Y"
                                        ]
                                        
                                        [span_113](start_span)for fmt in date_formats:[span_113](end_span)
                                            [span_114](start_span)try:[span_114](end_span)
                                                created_date = datetime.strptime(created_str, fmt)
                                                [span_115](start_span)break[span_115](end_span)
                                            except:
                                                continue
                                        # Missing 'else' logic addressed by handling timestamp below
                                        if not created_date:
                                            [span_116](start_span)try:[span_116](end_span)
                                                timestamp = float(created_str)
                                                [span_117](start_span)created_date = datetime.fromtimestamp(timestamp)[span_117](end_span)
                                            except:
                                                [span_118](start_span)created_date = None[span_118](end_span)
                                
                                except Exception:
                                    # Handle nested try/except issues
                                    pass

                                if created_date:
                                    [span_119](start_span)formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")[span_119](end_span)
                                else:
                                    [span_120](start_span)formatted_date = created_str  # Fallback to raw string[span_120](end_span)
                            except Exception as e:
                                [span_121](start_span)formatted_date = created_str  # Fallback to raw string[span_121](end_span)
                        
                        st.write(f"**Date:** {formatted_date}")
                        st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
                        st.write(f"**Progress:** Question {test['index'] + 1}/{test['total_questions']}")
                        [span_122](start_span)st.write(f"**System:** {test.get('system', 'All')}")[span_122](end_span)
                        
                        if st.button(f"Continue This Test", key=f"continue_{i}"):
                            [span_123](start_span)restored_questions = [][span_123](end_span)
                            for q_data in test["questions"]:
                                found = False
                                for original_q in QUESTIONS:
                                    [span_124](start_span)if original_q["id"] == q_data.get("id"):[span_124](end_span)
                                        restored_questions.append(original_q)
                                        [span_125](start_span)found = True[span_125](end_span)
                                        break
                                
                                [span_126](start_span)if not found:[span_126](end_span)
                                    restored_questions.append({
                                        [span_127](start_span)"id": q_data.get("id", ""),[span_127](end_span)
                                        "system": "Unknown",
                                        [span_128](start_span)"question": q_data.get("question", "Question not found"),[span_128](end_span)
                                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                        [span_129](start_span)"options": ["Option A", "Option B", "Option C", "Option D"],[span_129](end_span)
                                        "answer": q_data.get("answer", "A"),
                                        [span_130](start_span)"explanation": q_data.get("explanation", "")[span_130](end_span)
                                    })
                            
                            if restored_questions:
                                [span_131](start_span)st.session_state.test = {[span_131](end_span)
                                    "id": test["test_id"],
                                    "questions": restored_questions,
                                    [span_132](start_span)"answers": test["answers"],[span_132](end_span)
                                    "marked": test["marked"],
                                    "index": test["index"],
                                    [span_133](start_span)"mode": test["mode"],[span_133](end_span)
                                    "start": time.time(),
                                    "is_review": False
                                [span_134](start_span)}
                                st.session_state.page = "test"
                                st.rerun()
                
                st.divider()[span_134](end_span)
            
            if completed_tests:
                st.write(f"**Completed Tests ({len(completed_tests)})**")
                for i, test in enumerate(completed_tests):
                    [span_135](start_span)total_time = ""[span_135](end_span)
                    try:
                        if "start_time" in test:
                            [span_136](start_span)total_time = f" | Time: {format_time(test.get('duration', 0))}"[span_136](end_span)
                    except:
                        pass
                    
                    with st.expander(f"Test {i+1}: {test.get('mode', 'Unknown')} Mode - Score: {test['score']}/{test['total_questions']}{total_time}"):
                        # [span_137](start_span)FIXED: Improved date formatting (same as above)[span_137](end_span)
                        formatted_date = "Unknown date"
                        [span_138](start_span)created_str = test.get("created", "")[span_138](end_span)
                        
                        if created_str:
                            try:
                                [span_139](start_span)created_str = str(created_str).strip()[span_139](end_span)
                                
                                # Try to parse the date
                                created_date = None
                                
                                [span_140](start_span)try:[span_140](end_span)
                                    if 'T' in created_str:
                                        [span_141](start_span)if created_str.endswith('Z'):[span_141](end_span)
                                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                        [span_142](start_span)else:[span_142](end_span)
                                            if '+' in created_str or '-' in created_str[-6:]:
                                                [span_143](start_span)created_date = datetime.fromisoformat(created_str)[span_143](end_span)
                                            else:
                                                [span_144](start_span)created_date = datetime.fromisoformat(created_str + '+00:00')[span_144](end_span)
                                    else:
                                        [span_145](start_span)date_formats = [[span_145](end_span)
                                            "%Y-%m-%d %H:%M:%S.%f",
                                            [span_146](start_span)"%Y-%m-%d %H:%M:%S",[span_146](end_span)
                                            "%m/%d/%Y %H:%M:%S",
                                            [span_147](start_span)"%d/%m/%Y %H:%M:%S",[span_147](end_span)
                                            "%Y-%m-%d",
                                            [span_148](start_span)"%m/%d/%Y",[span_148](end_span)
                                            "%d/%m/%Y"
                                        ]
                                        
                                        [span_149](start_span)for fmt in date_formats:[span_149](end_span)
                                            try:
                                                [span_150](start_span)created_date = datetime.strptime(created_str, fmt)[span_150](end_span)
                                                break
                                            [span_151](start_span)except:[span_151](end_span)
                                                continue
                                        
                                        [span_152](start_span)if not created_date:[span_152](end_span)
                                            try:
                                                [span_153](start_span)timestamp = float(created_str)[span_153](end_span)
                                                created_date = datetime.fromtimestamp(timestamp)
                                            except:
                                                [span_154](start_span)created_date = None[span_154](end_span)
                                
                                except Exception:
                                    pass
                                
                                [span_155](start_span)if created_date:[span_155](end_span)
                                    formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                                else:
                                    [span_156](start_span)formatted_date = created_str[span_156](end_span)
                            except Exception as e:
                                formatted_date = created_str
                        
                        [span_157](start_span)st.write(f"**Date:** {formatted_date}")[span_157](end_span)
                        st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
                        st.write(f"**Questions:** {test['total_questions']}")
                        
                        # [span_158](start_span)FIXED: Added check to prevent division by zero[span_158](end_span)
                        if test['total_questions'] > 0:
                            [span_159](start_span)score_percentage = (test['score'] / test['total_questions']) * 100[span_159](end_span)
                            st.write(f"**Score:** {test['score']}/{test['total_questions']} ({score_percentage:.1f}%)")
                        else:
                            st.write(f"**Score:** {test['score']}/{test['total_questions']} (N/A%)")
                        
                        [span_160](start_span)st.write(f"**System:** {test.get('system', 'All')}")[span_160](end_span)
                        
                        if st.button(f"Review This Test", key=f"review_{i}"):
                            [span_161](start_span)restored_questions = [][span_161](end_span)
                            for q_data in test["questions"]:
                                found = False
                                [span_162](start_span)for original_q in QUESTIONS:[span_162](end_span)
                                    if original_q["id"] == q_data.get("id"):
                                        [span_163](start_span)restored_questions.append(original_q)[span_163](end_span)
                                        found = True
                                        break
                                
                                [span_164](start_span)if not found:[span_164](end_span)
                                    restored_questions.append({
                                        [span_165](start_span)"id": q_data.get("id", ""),[span_165](end_span)
                                        "system": "Unknown",
                                        [span_166](start_span)"question": q_data.get("question", "Question not found"),[span_166](end_span)
                                        "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                        [span_167](start_span)"options": ["Option A", "Option B", "Option C", "Option D"],[span_167](end_span)
                                        "answer": q_data.get("answer", "A"),
                                        [span_168](start_span)"explanation": q_data.get("explanation", "")[span_168](end_span)
                                    })
                            
                            if restored_questions:
                                [span_169](start_span)st.session_state.test = {[span_169](end_span)
                                    "id": test["test_id"],
                                    "questions": restored_questions,
                                    [span_170](start_span)"answers": test["answers"],[span_170](end_span)
                                    "marked": test["marked"],
                                    [span_171](start_span)"index": 0,[span_171](end_span)
                                    "mode": test["mode"],
                                    "is_review": True
                                [span_172](start_span)}
                                st.session_state.page = "test_review"
                                st.rerun()
            elif not incomplete_tests:
                st.info("No tests found. Create your first test!")[span_172](end_span)
    
    with tab2:
        st.subheader("📊 Your Analytics")
        
        prog = get_user_progress(st.session_state.user)
        user_tests = get_user_tests(st.session_state.user)
        completed_tests = [t for t in user_tests if t.get("completed", True)]
        
        # Basic stats
        [span_173](start_span)col1, col2, col3, col4 = st.columns(4)[span_173](end_span)
        
        total_questions = len(QUESTIONS)
        used_questions = len(prog["used"])
        unused_questions = total_questions - used_questions
        correct_questions = len(prog["correct"])
        incorrect_questions = len(prog["incorrect"])
        
        with col1:
            st.metric("Total Questions", total_questions)
        with col2:
            [span_174](start_span)st.metric("Unused Questions", unused_questions)[span_174](end_span)
        with col3:
            st.metric("Correct", correct_questions)
        with col4:
            st.metric("Incorrect", incorrect_questions)
        
        # Progress bar
        if total_questions > 0:
            [span_175](start_span)usage_percent = (used_questions / total_questions) * 100[span_175](end_span)
            st.progress(usage_percent / 100)
            st.write(f"**Question Usage:** {used_questions}/{total_questions} ({usage_percent:.1f}%)")
        else:
            st.progress(0)
            st.write("**Question Usage:** 0/0 (0%)")
        
        # Pie chart for performance
        if used_questions > 0:
            [span_176](start_span)fig = go.Figure(data=[go.Pie([span_176](end_span)
                labels=['Correct', 'Incorrect'],
                values=[correct_questions, incorrect_questions],
                hole=0.3,
                marker_colors=['green', 'red']
            )])
            [span_177](start_span)fig.update_layout(title_text="Question Performance")[span_177](end_span)
            st.plotly_chart(fig, use_container_width=True)
        else:
            [span_178](start_span)st.info("No questions answered yet. Start a test to see performance analytics.")[span_178](end_span)
        
        # Test history
        if completed_tests:
            st.subheader("Test History")
            dates = []
            scores = []
            
            [span_179](start_span)for test in completed_tests[-10:]:  # Last 10 tests[span_179](end_span)
                try:
                    # FIXED: Better date parsing for chart
                    created_date = None
                    created_str = test.get("created", "")
                    
                    [span_180](start_span)if created_str:[span_180](end_span)
                        created_str = str(created_str).strip()
                        
                        # [span_181](start_span)Try to parse the date[span_181](end_span)
                        try:
                            if 'T' in created_str:
                                # [span_182](start_span)ISO format[span_182](end_span)
                                if created_str.endswith('Z'):
                                    created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                [span_183](start_span)else:[span_183](end_span)
                                    if '+' in created_str or '-' in created_str[-6:]:
                                        created_date = datetime.fromisoformat(created_str)
                                    [span_184](start_span)else:[span_184](end_span)
                                        created_date = datetime.fromisoformat(created_str + '+00:00')
                            else:
                                # [span_185](start_span)Try other formats[span_185](end_span)
                                date_formats = [
                                    [span_186](start_span)"%Y-%m-%d %H:%M:%S.%f",[span_186](end_span)
                                    "%Y-%m-%d %H:%M:%S",
                                    [span_187](start_span)"%m/%d/%Y %H:%M:%S",[span_187](end_span)
                                    "%d/%m/%Y %H:%M:%S",
                                    "%Y-%m-%d",
                                    [span_188](start_span)"%m/%d/%Y",[span_188](end_span)
                                    "%d/%m/%Y"
                                ]
                                
                                [span_189](start_span)for fmt in date_formats:[span_189](end_span)
                                    try:
                                        [span_190](start_span)created_date = datetime.strptime(created_str, fmt)[span_190](end_span)
                                        break
                                    except:
                                        [span_191](start_span)continue[span_191](end_span)
                        except:
                            pass
                        
                        if created_date:
                            [span_192](start_span)date_str = created_date.strftime("%m/%d")[span_192](end_span)
                            dates.append(date_str)
                            
                            # FIXED: Prevent division by zero in analytics
                            [span_193](start_span)if test["total_questions"] > 0:[span_193](end_span)
                                percentage = (test["score"] / test["total_questions"]) * 100
                            else:
                                [span_194](start_span)percentage = 0[span_194](end_span)
                            scores.append(percentage)
                except Exception as e:
                    continue
            
            [span_195](start_span)if dates and scores:[span_195](end_span)
                fig2 = go.Figure(data=[go.Scatter(
                    x=dates,
                    y=scores,
                    mode='lines+markers',
                    [span_196](start_span)name='Score %'[span_196](end_span)
                )])
                fig2.update_layout(
                    title="Recent Test Performance",
                    xaxis_title="Test Date",
                    [span_197](start_span)yaxis_title="Score %",[span_197](end_span)
                    yaxis_range=[0, 100]
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                [span_198](start_span)st.info("Not enough test data to display performance chart.")[span_198](end_span)
    
    with tab3:
        st.subheader("▶️ Continue Last Test")
        
        user_tests = get_user_tests(st.session_state.user)
        incomplete_tests = [t for t in user_tests if not t.get("completed", True)]
        
        if incomplete_tests:
            test = incomplete_tests[0]
            
            # [span_199](start_span)FIXED: Better date formatting[span_199](end_span)
            formatted_date = "Unknown date"
            created_str = test.get("created", "")
            
            if created_str:
                try:
                    [span_200](start_span)created_str = str(created_str).strip()[span_200](end_span)
                    
                    # Try to parse the date
                    created_date = None
                    
                    [span_201](start_span)try:[span_201](end_span)
                        if 'T' in created_str:
                            if created_str.endswith('Z'):
                                [span_202](start_span)created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))[span_202](end_span)
                            else:
                                if '+' in created_str or '-' in created_str[-6:]:
                                    [span_203](start_span)created_date = datetime.fromisoformat(created_str)[span_203](end_span)
                                else:
                                    created_date = datetime.fromisoformat(created_str + '+00:00')
                        [span_204](start_span)else:[span_204](end_span)
                            date_formats = [
                                "%Y-%m-%d %H:%M:%S.%f",
                                [span_205](start_span)"%Y-%m-%d %H:%M:%S",[span_205](end_span)
                                "%m/%d/%Y %H:%M:%S",
                                "%d/%m/%Y %H:%M:%S",
                                "%Y-%m-%d",
                                [span_206](start_span)"%m/%d/%Y",[span_206](end_span)
                                "%d/%m/%Y"
                            ]
                            
                            [span_207](start_span)for fmt in date_formats:[span_207](end_span)
                                try:
                                    [span_208](start_span)created_date = datetime.strptime(created_str, fmt)[span_208](end_span)
                                    break
                                except:
                                    [span_209](start_span)continue[span_209](end_span)
                            # Implicit 'else' fixed with explicit check
                            if not created_date:
                                [span_210](start_span)created_date = None[span_210](end_span)
                    except:
                        pass
                        
                    if created_date:
                        formatted_date = created_date.strftime("%B %d, %Y at %I:%M %p")
                    else:
                        [span_211](start_span)formatted_date = created_str[span_211](end_span)
                except Exception as e:
                    formatted_date = created_str
            
            st.write(f"**Last Incomplete Test**")
            st.write(f"**Date:** {formatted_date}")
            st.write(f"**Mode:** {test.get('mode', 'Unknown')}")
            [span_212](start_span)st.write(f"**Progress:** Question {test['index'] + 1}/{test['total_questions']}")[span_212](end_span)
            st.write(f"**System:** {test.get('system', 'All')}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Continue Test", use_container_width=True):
                    [span_213](start_span)restored_questions = [][span_213](end_span)
                    for q_data in test["questions"]:
                        found = False
                        for original_q in QUESTIONS:
                            [span_214](start_span)if original_q["id"] == q_data.get("id"):[span_214](end_span)
                                restored_questions.append(original_q)
                                found = True
                                [span_215](start_span)break[span_215](end_span)
                        
                        if not found:
                            [span_216](start_span)restored_questions.append({[span_216](end_span)
                                "id": q_data.get("id", ""),
                                "system": "Unknown",
                                [span_217](start_span)"question": q_data.get("question", "Question not found"),[span_217](end_span)
                                "options_map": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                                "options": ["Option A", "Option B", "Option C", "Option D"],
                                [span_218](start_span)"answer": q_data.get("answer", "A"),[span_218](end_span)
                                "explanation": q_data.get("explanation", "")
                            })
                    
                    [span_219](start_span)if restored_questions:[span_219](end_span)
                        st.session_state.test = {
                            "id": test["test_id"],
                            [span_220](start_span)"questions": restored_questions,[span_220](end_span)
                            "answers": test["answers"],
                            "marked": test["marked"],
                            "index": test["index"],
                            [span_221](start_span)"mode": test["mode"],[span_221](end_span)
                            "start": time.time(),
                            "is_review": False
                        [span_222](start_span)}
                        st.session_state.page = "test"
                        st.rerun()
            
            with col2:
                if st.button("Start New Test Instead", use_container_width=True):[span_222](end_span)
                    st.session_state.page = "create"
                    st.rerun()
        else:
            [span_223](start_span)st.info("No incomplete tests found. All tests are completed!")[span_223](end_span)
            if st.button("Create New Test", use_container_width=True):
                st.session_state.page = "create"
                st.rerun()
    
    st.stop()

# ================= CREATE TEST PAGE =================
if st.session_state.page == "create":
    st.title("🧪 Create New Test")
    
    if st.button("← Back"):
        go_back()
    
    [span_224](start_span)prog = get_user_progress(st.session_state.user)[span_224](end_span)
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
        [span_225](start_span)pool = [q for q in pool if q["system"] in systems][span_225](end_span)
    
    if "All" not in filters:
        if "Unused" in filters:
            pool = [q for q in pool if q["id"] not in prog["used"]]
        if "Correct" in filters:
            pool = [q for q in pool if q["id"] in prog["correct"]]
        [span_226](start_span)if "Incorrect" in filters:[span_226](end_span)
            pool = [q for q in pool if q["id"] in prog["incorrect"]]
        if "Marked" in filters:
            pool = [q for q in pool if q["id"] in prog["marked"]]
    
    if mode == "Test":
        total_seconds = calculate_total_test_time(num_q)
        hours = total_seconds // 3600
        [span_227](start_span)minutes = (total_seconds % 3600) // 60[span_227](end_span)
        time_str = f"{hours} hour{'' if hours == 1 else 's'} {minutes} minute{'' if minutes == 1 else 's'}" if hours > 0 else f"{minutes} minute{'' if minutes == 1 else 's'}"
        st.info(f"**Estimated test time:** {time_str} ({num_q} questions × 90 seconds each)")
    
    st.info(f"Available questions: {len(pool)}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        [span_228](start_span)if st.button("Cancel", use_container_width=True):[span_228](end_span)
            go_back()
    
    with col2:
        if st.button("Start Test", use_container_width=True):
            if len(pool) < num_q:
                [span_229](start_span)st.error(f"Not enough questions available. Only {len(pool)} questions match your criteria.")[span_229](end_span)
            else:
                selected = random.sample(pool, min(num_q, len(pool)))
                st.session_state.test = {
                    "id": str(uuid.uuid4()),
                    "questions": selected,
                    [span_230](start_span)"answers": {},[span_230](end_span)
                    "marked": set(),
                    "index": 0,
                    "mode": mode,
                    [span_231](start_span)"start": time.time(),[span_231](end_span)
                    "is_review": False
                }
                save_test_session(st.session_state.user, st.session_state.test, completed=False)
                st.session_state.page = "test"
                st.rerun()
    
    st.stop()

# [span_232](start_span)================= TEST PAGE =================[span_232](end_span)
if st.session_state.page == "test":
    # FIX: Clear any cached content from Create Test page
    if st.session_state.get("clear_cache_on_test", False):
        # Clear the cache flag
        st.session_state.clear_cache_on_test = False
        # Force a rerun to ensure clean state
        st.rerun()
    
    if st.session_state.test is None:
        [span_233](start_span)st.error("No test session found. Returning to home.")[span_233](end_span)
        st.session_state.page = "home"
        st.rerun()
    
    test = st.session_state.test
    q = test["questions"][test["index"]]
    
    # Check if time is up for Test mode
    if test["mode"] == "Test" and not test.get("is_review"):
        time_up = update_timer(test)
        if time_up or st.session_state.time_up:
            save_current_answer(test, q)
            [span_234](start_span)save_test_session(st.session_state.user, test, completed=True)[span_234](end_span)
            st.session_state.page = "review"
            st.rerun()
    
    # Header with timer for Test mode
    if test["mode"] == "Test" and not test.get("is_review"):
        # FIXED: Clean header without Create Test page elements
        col_head1, col_head2, col_head3, col_head4 = st.columns([2, 3, 2, 1])
        [span_235](start_span)with col_head1:[span_235](end_span)
            st.write(f"**Mode:** {test['mode']}")
        with col_head2:
            st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")
        with col_head3:
            elapsed_str = format_time(st.session_state.timer_elapsed)
            remaining_str = format_time(st.session_state.timer_remaining)
            
            [span_236](start_span)total_time = calculate_total_test_time(len(test["questions"]))[span_236](end_span)
            warning_threshold = total_time * 0.1
            
            if st.session_state.timer_remaining <= warning_threshold:
                [span_237](start_span)st.warning(f"⏰ Time: {elapsed_str} | Remaining: {remaining_str}")[span_237](end_span)
            else:
                st.info(f"⏰ Time: {elapsed_str} | Remaining: {remaining_str}")
        with col_head4:
            if st.button("🏠 End & Save", type="secondary", use_container_width=True):
                save_current_answer(test, q)
                save_test_session(st.session_state.user, test, completed=False)
                [span_238](start_span)st.session_state.page = "home"[span_238](end_span)
                st.rerun()
    else:
        # Reading mode header
        col_head1, col_head2, col_head3 = st.columns([2, 3, 1])
        with col_head1:
            st.write(f"**Mode:** {test['mode']}")
        with col_head2:
            [span_239](start_span)st.title(f"Question {test['index'] + 1}/{len(test['questions'])}")[span_239](end_span)
        with col_head3:
            if st.button("🏠 End & Save", type="secondary", use_container_width=True):
                save_current_answer(test, q)
                save_test_session(st.session_state.user, test, completed=False)
                st.session_state.page = "home"
                [span_240](start_span)st.rerun()[span_240](end_span)
    
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
        [span_241](start_span)q["options"],[span_241](end_span)
        index=q["options"].index(current_answer) if current_answer in q["options"] else None,
        key=radio_key
    )
    
    # Update session state
    if choice:
        st.session_state.current_choice = choice
        save_current_answer(test, q)
    
    # Navigation buttons - FIXED: Clean layout without Create Test elements
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        [span_242](start_span)if st.button("⬅ Previous", use_container_width=True, disabled=test["index"] == 0):[span_242](end_span)
            save_current_answer(test, q)
            test["index"] -= 1
            st.rerun()
    
    with col2:
        next_text = "Finish" if test["index"] == len(test["questions"]) - 1 else "Next ➡"
        if st.button(next_text, use_container_width=True):
            [span_243](start_span)save_current_answer(test, q)[span_243](end_span)
            if test["index"] < len(test["questions"]) - 1:
                test["index"] += 1
                st.rerun()
            else:
                st.session_state.page = "review"
                st.rerun()
    
    [span_244](start_span)with col3:[span_244](end_span)
        if q["id"] in test["marked"]:
            if st.button("✅ Unmark", use_container_width=True):
                test["marked"].remove(q["id"])
                st.rerun()
        else:
            if st.button("🚩 Mark", use_container_width=True):
                [span_245](start_span)test["marked"].add(q["id"])[span_245](end_span)
                st.rerun()
    
    with col4:
        question_numbers = list(range(1, len(test["questions"]) + 1))
        selected_q = st.selectbox(
            "Jump to",
            question_numbers,
            index=test["index"],
            [span_246](start_span)key=f"jump_{test['index']}",[span_246](end_span)
            label_visibility="collapsed"
        )
        if selected_q - 1 != test["index"]:
            save_current_answer(test, q)
            test["index"] = selected_q - 1
            st.rerun()
    
    # Reading mode answer display
    if test["mode"] == "Reading" and choice:
        [span_247](start_span)st.divider()[span_247](end_span)
        user_choice = choice
        correct_answer = q["answer"]
        explanation = q.get("explanation", "No explanation provided.")
        
        user_letter = None
        for k, v in q["options_map"].items():
            if v == user_choice:
                [span_248](start_span)user_letter = k[span_248](end_span)
                break
        
        if user_letter == correct_answer:
            st.success(f"**Correct!** ({correct_answer})")
        else:
            st.error(f"**Incorrect.** You chose {user_letter}, correct is {correct_answer}")
        
        st.info(f"**Explanation:** {explanation}")
    
    # [span_249](start_span)Auto-refresh for timer in Test mode - FIXED: Moved to bottom to prevent cache issues[span_249](end_span)
    if test["mode"] == "Test" and not test.get("is_review"):
        time.sleep(1)
        st.rerun()
    
    st.stop()

# ================= TEST REVIEW MODE =================
if st.session_state.page == "test_review":
    if st.session_state.test is None:
        [span_250](start_span)st.error("No test to review. Returning to home.")[span_250](end_span)
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
        [span_251](start_span)if st.button("🏠 Home", use_container_width=True):[span_251](end_span)
            st.session_state.page = "home"
            st.rerun()
    
    st.divider()
    
    # Question display
    st.markdown(f"**{q['question']}**")
    
    # Display all options with correct/incorrect highlighting
    user_answer = test["answers"].get(q["id"])
    correct_answer = q["answer"]
    
    for letter, option_text in q["options_map"].items():
        if option_text:
            [span_252](start_span)col_option1, col_option2 = st.columns([1, 20])[span_252](end_span)
            with col_option1:
                if letter == correct_answer:
                    st.success(f"**{letter}**")
                elif letter == user_answer:
                    [span_253](start_span)st.error(f"**{letter}**")[span_253](end_span)
                else:
                    st.write(f"**{letter}**")
            with col_option2:
                if letter == correct_answer:
                    st.success(option_text)
                [span_254](start_span)elif letter == user_answer:[span_254](end_span)
                    st.error(option_text)
                else:
                    st.write(option_text)
    
    # Explanation
    st.divider()
    st.subheader("Explanation")
    explanation = q.get("explanation", "No explanation provided.")
    [span_255](start_span)st.info(explanation)[span_255](end_span)
    
    # Navigation
    col_nav1, col_nav2, col_nav3 = st.columns(3)
    
    with col_nav1:
        if st.button("⬅ Previous", use_container_width=True, disabled=test["index"] == 0):
            test["index"] -= 1
            st.rerun()
    
    with col_nav2:
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = "home"
            [span_256](start_span)st.rerun()[span_256](end_span)
    
    with col_nav3:
        next_disabled = test["index"] == len(test["questions"]) - 1
        if st.button("Next ➡", use_container_width=True, disabled=next_disabled):
            test["index"] += 1
            st.rerun()
    
    st.stop()

# ================= REVIEW/SCORE PAGE =================
if st.session_state.page == "review":
    if st.session_state.test is None:
        [span_257](start_span)st.error("No test to review. Returning to home.")[span_257](end_span)
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
        [span_258](start_span)if test["answers"].get(qid) == q["answer"]:[span_258](end_span)
            correct += 1
            prog["correct"].add(qid)
            if qid in prog["incorrect"]:
                prog["incorrect"].remove(qid)
        else:
            prog["incorrect"].add(qid)
            if qid in prog["correct"]:
                [span_259](start_span)prog["correct"].remove(qid)[span_259](end_span)
    
    prog["marked"].update(test["marked"])
    
    total = len(test["questions"])
    score_percent = (correct / total * 100) if total > 0 else 0
    
    # Display metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Score", f"{correct}/{total}")
    
    with col2:
        [span_260](start_span)st.metric("Percentage", f"{score_percent:.1f}%")[span_260](end_span)
    
    with col3:
        if test["mode"] == "Test" and "start" in test:
            elapsed = int(time.time() - test["start"])
            time_str = format_time(elapsed)
            st.metric("Time Taken", time_str)
        else:
            if score_percent >= 70:
                [span_261](start_span)st.success("🎉 Excellent!")[span_261](end_span)
            elif score_percent >= 60:
                st.info("👍 Good")
            else:
                st.warning("📚 Needs Improvement")
    
    # Pie chart
    fig = go.Figure(data=[go.Pie(
        labels=['Correct', 'Incorrect'],
        [span_262](start_span)values=[correct, total - correct],[span_262](end_span)
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
        [span_263](start_span)with st.expander(f"Question {i + 1}: {'✅' if test['answers'].get(q['id']) == q['answer'] else '❌'}"):[span_263](end_span)
            st.write(f"**Question:** {q['question'][:100]}...")
            user_answer = test["answers"].get(q["id"])
            st.write(f"**Your answer:** {user_answer if user_answer else 'Not answered'}")
            st.write(f"**Correct answer:** {q['answer']}")
            st.write(f"**Explanation:** {q.get('explanation', 'No explanation provided.')}")
    
    # Action buttons
    [span_264](start_span)col_btn1, col_btn2, col_btn3 = st.columns(3)[span_264](end_span)
    
    with col_btn1:
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    
    with col_btn2:
        if st.button("📊 Analytics", use_container_width=True):
            st.session_state.page = "previous_menu"
            st.rerun()
    
    with col_btn3:
        [span_265](start_span)if st.button("🔍 Review Test", use_container_width=True):[span_265](end_span)
            test["is_review"] = True
            test["index"] = 0
            st.session_state.page = "test_review"
            st.rerun()
    
    st.stop()
