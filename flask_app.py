import os
import json
import time
from flask import Flask, request, jsonify, render_template

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
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
    return default_value

USERS = load_json(USERS_FILE, {})
QUESTIONS = load_json(QUESTIONS_FILE, [])

logged_in_users = {}

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
    מנקה תווים המשתמשים כמפרידים במערכת ימות המשיח (שווה, מקף, פסיק, מרכאות)
    כדי למנוע שבירה של פורמט ה-read=t-TEXT...
    """
    if not text:
        return ""
    text = str(text)
    replacements = {
        '=': ' ',
        '-': ' ',
        ',': ' ',
        '"': '',
        "'": '',
        '&': ' ',
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
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/yemot', methods=['GET', 'POST'])
def yemot_api():
    phone = request.values.get('ApiPhone', '0000000')
    call_id = request.values.get('ApiCallId', phone)
    
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
                return f"read=t-{clean_name} נרשמת בהצלחה אנא המתן לתחילת המשחק=WaitLobby,no,1,1,5,No,No,1"
            else:
                return "read=t-מספר שגוי נסה שוב=UserId,no,2,1,10,No"
        else:
            return "read=t-ברוכים הבאים למשחק הטריויה נא להקיש מספר משתתף וסולמית=UserId,no,2,1,10,No"

    participant_id = logged_in_users[call_id]
    
    # שלב ב': בדיקת סטטוס המשחק
    st = game_state["status"]
    idx = game_state["question_index"]

    if st == "lobby":
        return "read=t-אנא המתן לתחילת המשחק=WaitLobby,no,1,1,5,No,No,1"
        
    if st == "pause":
        return "read=t-המשחק מושהה אנא המתן=WaitPause,no,1,1,5,No,No,1"

    if st == "mid_leaderboard":
        return "read=t-תוצאות ביניים מוצגות במסך אנא המתן=WaitMid,no,1,1,5,No,No,1"

    if st == "endgame":
        return "read=t-המשחק הסתיים תודה רבה על השתתפותכם=WaitEnd,no,1,1,5,No,No,1"

    if st == "reveal":
        return f"read=t-ההצבעה נסגרה אנא המתן לתוצאות=WaitRev_{idx},no,1,1,5,No,No,1"

    # שלב ג': משחק פעיל (active)
    if st == "active":
        # אם המשתמש כבר ענה על השאלה הנוכחית
        if participant_id in game_state["answers"]:
            return f"read=t-תשובתך נקלטה אנא המתן=WaitAns_{idx},no,1,1,5,No,No,1"

        # שולפים קלט ספציפי לשאלה הנוכחית (Answer_Q0, Answer_Q1, וכו')
        param_name = f"Answer_Q{idx}"
        answer_input = get_targeted_input(param_name)

        if answer_input and answer_input in ["1", "2", "3", "4"]: 
            if idx < len(QUESTIONS):
                time_taken = round(time.time() - game_state["start_time"], 2)
                current_q = QUESTIONS[idx]
                is_correct = (answer_input == str(current_q.get("correct_answer", "")))

                game_state["answers"][participant_id] = {
                    "name": USERS.get(participant_id, participant_id),
                    "time": time_taken,
                    "correct": is_correct,
                    "choice": answer_input
                }
            return f"read=t-תשובתך התקבלה אנא המתן=WaitAns_{idx},no,1,1,5,No,No,1"
        else:
            return f"read=t-הקש את מספר התשובה=Answer_Q{idx},no,1,1,8,No"

    return f"read=t-אנא המתן=WaitGen_{idx},no,1,1,5,No,No,1"

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
        for pid, data in game_state["answers"].items():
            if data["correct"]:
                if pid in game_state["global_scores"]:
                    game_state["global_scores"][pid]["score"] += 1
                    game_state["global_scores"][pid]["time"] += data["time"]

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

    return jsonify({"success": True, "status": game_state["status"], "question_index": game_state["question_index"]})

@app.route('/api/admin/prev', methods=['POST'])
def prev_question():
    if game_state["question_index"] > 0:
        game_state["question_index"] -= 1
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
        game_state["answers"] = {}
    return jsonify({"success": True, "status": game_state["status"], "question_index": game_state["question_index"]})

@app.route('/api/admin/pause', methods=['POST'])
def toggle_pause():
    if game_state["status"] in ["active", "reveal"]:
        game_state["status"] = "pause"
    elif game_state["status"] == "pause":
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
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
    return jsonify({"success": True, "message": "Game reset successfully"})

@app.route('/api/admin/reload', methods=['POST'])
def reload_data():
    global USERS, QUESTIONS
    USERS = load_json(USERS_FILE, {})
    QUESTIONS = load_json(QUESTIONS_FILE, [])
    return jsonify({
        "success": True,
        "users_count": len(USERS),
        "questions_count": len(QUESTIONS)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)