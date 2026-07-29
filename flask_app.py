import os
import json
import time
import logging
import sys
from flask import Flask, request, jsonify, render_template

# הגדרת מנגנון הלוגים (Logging)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger("yemot_trivia")

app = Flask(__name__)
application = app  # שורת החובה עבור השרת של PythonAnywhere

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
QUESTIONS_FILE = os.path.join(DATA_DIR, 'questions.json')

# ==========================================
# 1. טעינת נתונים מקבצי JSON
# ==========================================
def load_json(filepath, default_value):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Loaded JSON successfully from {os.path.basename(filepath)} ({len(data)} items)")
                return data
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
    else:
        logger.warning(f"File not found: {filepath}")
    return default_value

USERS = load_json(USERS_FILE, {})
QUESTIONS = load_json(QUESTIONS_FILE, [])

logged_in_users = {}
last_prompt_spoken = {}

# ==========================================
# 2. ניהול מצב המערכת
# ==========================================
game_state = {
    "question_index": 0,
    "status": "lobby",
    "start_time": 0,
    "answers": {},
    "connected_players": {},
    "global_scores": {}
}

# ==========================================
# 3. פונקציות עזר וסניטציה עבור ימות המשיח
# ==========================================
def sanitize_tts_text(text):
    """
    מנקה תווים המשתמשים כמפרידים במערכת ימות המשיח (שווה, מקף, פסיק, נקודה, מרכאות)
    כדי למנוע שבירה של פורמט ה-read=t-TEXT...
    """
    if not text:
        return ""
    text = str(text)
    replacements = {
        '=': ' ',
        '-': ' ',
        ',': ' ',
        '.': ' ',
        '"': '',
        "'": '',
        '&': ' ',
        '?': '',
        '!': '',
        '\n': ' ',
        '\r': ''
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()

def get_targeted_input(param_name):
    """
    שולף בצורה בטוחה ומדויקת את הקלט שנשלח עבור הפרמטר הספציפי (param_name).
    מונע זליגה של מקשים שנלחצו בשאלות קודמות ב-URL.
    """
    values = request.values.getlist(param_name)
    if not values:
        return None
    
    # שולפים את הערך האחרון שנשלח עבור פרמטר זה
    raw_val = values[-1]
    if raw_val is None:
        return None
        
    val = str(raw_val).strip()
    if ',' in val:
        val = val.split(',')[-1].strip()
        
    return val if val != "" else None

# ==========================================
# 4. נתיבי השרת (Routes) עבור ימות המשיח
# ==========================================
def extract_spoken_text(yemot_response):
    """
    מחלץ את הטקסט המדובר שיושמע למשתמש מתוך פורמט התשובה של ימות המשיח (read=t-TEXT=...)
    """
    if isinstance(yemot_response, str) and yemot_response.startswith("read=t-"):
        content = yemot_response[len("read=t-"):]
        spoken = content.split('=')[0]
        return spoken
    return str(yemot_response)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/yemot', methods=['GET', 'POST'])
def yemot_api():
    phone = request.values.get('ApiPhone', '0000000')
    call_id = request.values.get('ApiCallId', phone)
    
    def respond(res_text):
        spoken = extract_spoken_text(res_text)
        logger.info(f"[YEMOT OUTGOING] CallId={call_id} | User hears: '{spoken}'")
        logger.debug(f"[YEMOT RAW RESPONSE] CallId={call_id} | Full: {res_text}")
        return res_text

    def get_prompt_text(prompt_key, full_text):
        """
        משמיע את ההודעה המלאה בפעם הראשונה שנכנסים למצב,
        ואח"כ בבדיקות חוזרות באותו מצב מחזיר רווח (שקט) כדי לא לחזור על ההודעה בלופ.
        """
        if last_prompt_spoken.get(call_id) == prompt_key:
            return " "
        last_prompt_spoken[call_id] = prompt_key
        return full_text

    # ניתוק שיחה: ימות המשיח שולח hangup=yes בבקשה האחרונה עבור השיחה.
    # מנקים את הזיכרון של השיחה כדי לא לצבור דליפת זיכרון לאורך זמן.
    if request.values.get('hangup') == 'yes':
        hung_up_participant_id = logged_in_users.pop(call_id, None)
        last_prompt_spoken.pop(call_id, None)
        if hung_up_participant_id is not None:
            game_state["connected_players"].pop(hung_up_participant_id, None)
        logger.info(f"[YEMOT HANGUP] CallId={call_id}, Phone={phone} -> Cleaned up call state")
        return respond("")

    # לוג כל הפרמטרים שנשלחו ע"י ימות המשיח (כולל URL מלא)
    full_url = request.url
    logger.info(f"[YEMOT REQUEST] CallId={call_id}, Phone={phone} | URL: {full_url}")

    # לוג מקשי מקלדת / פרמטרים שנשלחו ע"י המשתמש (סינון פרמטרים טכניים של ימות המשיח)
    user_inputs = {
        k: v for k, v in request.values.items() 
        if not (k.startswith('Api') or k.startswith('Wait') or k in ['hangup']) and v != ''
    }
    if user_inputs:
        logger.info(f"[YEMOT INCOMING INPUT] CallId={call_id}, Phone={phone} -> User pressed/sent: {user_inputs}")

    # ==============================================================
    # פורמט read מהדוקומנטציה הרשמית של ימות המשיח:
    # VARNAME, use_existing, max, min, sec, play_type, block_asterisk,
    # block_zero, replace_char, allowed_digits, repeat_count, on_empty, empty_val
    #
    # המתנה (polling): sec=1 (פולינג מהיר כל שנייה), min=0, on_empty(12)=Ok
    # קלט מהמשתמש:    min=1, allowed_digits=1234
    # ==============================================================

    # שלב א': זיהוי משתתף
    if call_id not in logged_in_users:
        user_id_input = get_targeted_input('UserId')

        if user_id_input:
            if user_id_input in USERS:
                logged_in_users[call_id] = user_id_input
                user_name = USERS[user_id_input]
                game_state["connected_players"][user_id_input] = user_name

                if user_id_input not in game_state["global_scores"]:
                    game_state["global_scores"][user_id_input] = {
                        "name": user_name,
                        "score": 0,
                        "time": 0.0
                    }

                clean_name = sanitize_tts_text(user_name)
                logger.info(f"[YEMOT LOGIN SUCCESS] CallId={call_id}, Phone={phone} -> UserId={user_id_input} ({user_name})")
                last_prompt_spoken[call_id] = "lobby"
                return respond(f"read=t-{clean_name} נרשמת בהצלחה אנא המתן לתחילת המשחק=WaitLobby,,1,0,1,No,,,,,1,Ok,None")
            else:
                logger.warning(f"[YEMOT LOGIN FAILED] CallId={call_id}, Phone={phone} tried invalid UserId='{user_id_input}'")
                last_prompt_spoken[call_id] = "login_failed"
                return respond("read=t-מספר שגוי נסה שוב=UserId,,2,1,10,No,,,,,,,,no")
        else:
            logger.debug(f"[YEMOT LOGIN PROMPT] CallId={call_id}, Phone={phone}")
            last_prompt_spoken[call_id] = "login_prompt"
            return respond("read=t-ברוכים הבאים למשחק הטריויה נא להקיש מספר משתתף וסולמית=UserId,,2,1,10,No,,,,,,,,no")

    participant_id = logged_in_users[call_id]
    
    # שלב ב': בדיקת סטטוס המשחק
    st = game_state["status"]
    idx = game_state["question_index"]
    logger.info(f"[YEMOT GAME CHECK] CallId={call_id}, User={participant_id}, Status='{st}', Q{idx}")

    if st == "lobby":
        txt = get_prompt_text("lobby", "אנא המתן לתחילת המשחק")
        return respond(f"read=t-{txt}=WaitLobby,,1,0,1,No,,,,,1,Ok,None")
        
    if st == "pause":
        txt = get_prompt_text("pause", "המשחק מושהה אנא המתן")
        return respond(f"read=t-{txt}=WaitPause,,1,0,1,No,,,,,1,Ok,None")

    if st == "mid_leaderboard":
        txt = get_prompt_text("mid_leaderboard", "תוצאות ביניים מוצגות במסך אנא המתן")
        return respond(f"read=t-{txt}=WaitMid,,1,0,1,No,,,,,1,Ok,None")

    if st == "endgame":
        txt = get_prompt_text("endgame", "המשחק הסתיים תודה רבה על השתתפותכם")
        return respond(f"read=t-{txt}=WaitEnd,,1,0,1,No,,,,,1,Ok,None")

    if st == "reveal":
        current_q = QUESTIONS[idx] if idx < len(QUESTIONS) else {}
        is_poll = (current_q.get("type") == "poll")
        if is_poll:
            reveal_msg = "ההצבעה לסקר נסגרה תודה על השתתפותכם אנא המתן לתוצאות"
        else:
            correct_ans = str(current_q.get("correct_answer", ""))
            reveal_msg = f"ההצבעה נסגרה התשובה הנכונה היא תשובה {correct_ans} אנא המתן לתוצאות" if correct_ans else "ההצבעה נסגרה אנא המתן לתוצאות"
        txt = get_prompt_text(f"reveal_{idx}", reveal_msg)
        return respond(f"read=t-{txt}=WaitRev_{idx},,1,0,1,No,,,,,1,Ok,None")

    # שלב ג': משחק פעיל (active)
    if st == "active":
        # אם המשתמש כבר ענה על השאלה הנוכחית - המתנה: sec=1, on_empty=Ok
        if participant_id in game_state["answers"]:
            txt = get_prompt_text(f"WaitAns_{idx}", "תשובתך נקלטה אנא המתן")
            return respond(f"read=t-{txt}=WaitAns_{idx},,1,0,1,No,,,,,1,Ok,None")

        # שולפים קלט ספציפי לשאלה הנוכחית (Answer_Q0, Answer_Q1, וכו')
        param_name = f"Answer_Q{idx}"
        answer_input = get_targeted_input(param_name)

        if answer_input and answer_input in ["1", "2", "3", "4"]: 
            if idx < len(QUESTIONS):
                time_taken = round(time.time() - game_state["start_time"], 2)
                current_q = QUESTIONS[idx]
                is_poll = (current_q.get("type") == "poll")
                is_correct = (answer_input == str(current_q.get("correct_answer", ""))) if not is_poll else False

                game_state["answers"][participant_id] = {
                    "name": USERS.get(participant_id, participant_id),
                    "time": time_taken,
                    "correct": is_correct,
                    "choice": answer_input,
                    "is_poll": is_poll
                }
                logger.info(f"[YEMOT ANSWER] User={participant_id} ({USERS.get(participant_id, '')}), Q{idx}, Choice={answer_input}, Correct={is_correct}, Time={time_taken}s, Poll={is_poll}")
            
            last_prompt_spoken[call_id] = f"WaitAns_{idx}"
            return respond(f"read=t-תשובתך התקבלה אנא המתן=WaitAns_{idx},,1,0,1,No,,,,,1,Ok,None")
        else:
            # בקשת תשובה: max=1, min=1, sec=10, allowed=1234, no (אישור הקשה)
            if idx < len(QUESTIONS):
                current_q = QUESTIONS[idx]
                is_poll = (current_q.get("type") == "poll")
                q_text = sanitize_tts_text(current_q.get("text", ""))
                options = current_q.get("options", [])
                opt_parts = [f"לאופציה {i+1} {sanitize_tts_text(opt)}" if is_poll else f"לתשובה {i+1} {sanitize_tts_text(opt)}" for i, opt in enumerate(options)]
                opt_str = " ".join(opt_parts)
                prompt_prefix = f"סקר {idx + 1}" if is_poll else f"שאלה {idx + 1}"
                prompt_suffix = "הקש את מספר האופציה הנבחרת" if is_poll else "הקש את מספר התשובה"
                full_prompt = f"{prompt_prefix} {q_text} {opt_str} {prompt_suffix}"
            else:
                full_prompt = "הקש את מספר התשובה"
            last_prompt_spoken[call_id] = f"question_{idx}"
            return respond(f"read=t-{full_prompt}=Answer_Q{idx},,1,1,10,No,,,,1234,,,,,no")

    txt = get_prompt_text(f"WaitGen_{idx}", "אנא המתן")
    return respond(f"read=t-{txt}=WaitGen_{idx},,1,0,1,No,,,,,1,Ok,None")

# ==========================================
# 5. נתיב תצוגה ללוח הבקרה (Display API)
# ==========================================
@app.route('/display', methods=['GET'])
def display():
    idx = game_state["question_index"]
    current_q = QUESTIONS[idx] if idx < len(QUESTIONS) else None
    return jsonify({
        "status": game_state["status"],
        "question": current_q,
        "answers": game_state["answers"],
        "connected_players": game_state["connected_players"],
        "global_scores": game_state["global_scores"],
        "question_index": idx,
        "total_questions": len(QUESTIONS)
    })

# ==========================================
# 6. פקודות ניהול (Admin API)
# ==========================================
@app.route('/api/admin/auto_next', methods=['POST'])
def auto_next():
    st = game_state["status"]
    idx = game_state["question_index"]

    if st == "lobby" or st == "pause":
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
        if st == "lobby":
            game_state["answers"] = {}

    elif st == "active":
        game_state["status"] = "reveal"
        correct_count = 0
        total_answers = len(game_state["answers"])
        current_q = QUESTIONS[idx] if idx < len(QUESTIONS) else {}
        is_poll = (current_q.get("type") == "poll")

        for pid, data in game_state["answers"].items():
            if not is_poll and data.get("correct"):
                correct_count += 1
                if pid in game_state["global_scores"]:
                    game_state["global_scores"][pid]["score"] += 1
                    game_state["global_scores"][pid]["time"] += data["time"]
        
        if is_poll:
            logger.info(f"[POLL REVEAL] Q{idx} ended. Submissions: {total_answers}")
        else:
            logger.info(f"[GAME REVEAL] Q{idx} ended. Submissions: {total_answers}, Correct: {correct_count}")


    elif st == "reveal":
        if idx >= len(QUESTIONS) - 1:
            game_state["status"] = "endgame"
        elif (idx + 1) % 10 == 0:
            game_state["status"] = "mid_leaderboard"
        else:
            game_state["question_index"] += 1
            game_state["status"] = "active"
            game_state["start_time"] = time.time()
            game_state["answers"] = {}

    elif st == "mid_leaderboard":
        game_state["question_index"] += 1
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
        game_state["answers"] = {}

    logger.info(f"[ADMIN AUTO_NEXT] State changed: '{st}' (Q{idx}) -> '{game_state['status']}' (Q{game_state['question_index']})")
    return jsonify({"success": True, "status": game_state["status"], "question_index": game_state["question_index"]})

@app.route('/api/admin/prev', methods=['POST'])
def prev_question():
    old_idx = game_state["question_index"]
    if game_state["question_index"] > 0:
        game_state["question_index"] -= 1
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
        game_state["answers"] = {}
        logger.info(f"[ADMIN PREV] Question index moved from Q{old_idx} to Q{game_state['question_index']}")
    return jsonify({"success": True, "status": game_state["status"], "question_index": game_state["question_index"]})

@app.route('/api/admin/pause', methods=['POST'])
def toggle_pause():
    old_st = game_state["status"]
    if game_state["status"] in ["active", "reveal"]:
        game_state["status"] = "pause"
    elif game_state["status"] == "pause":
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
    logger.info(f"[ADMIN PAUSE] Status toggled: '{old_st}' -> '{game_state['status']}'")
    return jsonify({"success": True, "status": game_state["status"]})

@app.route('/api/admin/reset', methods=['POST'])
def reset_game():
    game_state["question_index"] = 0
    game_state["status"] = "lobby"
    game_state["start_time"] = 0
    game_state["answers"] = {}
    game_state["connected_players"] = {}
    game_state["global_scores"] = {}
    logged_in_users.clear()
    last_prompt_spoken.clear()
    logger.info("[ADMIN RESET] Game state and connected users completely reset")
    return jsonify({"success": True, "message": "Game reset successfully"})

@app.route('/api/admin/reload', methods=['POST'])
def reload_data():
    global USERS, QUESTIONS
    USERS = load_json(USERS_FILE, {})
    QUESTIONS = load_json(QUESTIONS_FILE, [])
    logger.info(f"[ADMIN RELOAD] Data reloaded: {len(USERS)} users, {len(QUESTIONS)} questions")
    return jsonify({
        "success": True,
        "users_count": len(USERS),
        "questions_count": len(QUESTIONS)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)