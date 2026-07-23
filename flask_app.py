from flask import Flask, request, jsonify, render_template
import time

app = Flask(__name__)
application = app  # שורת החובה עבור השרת של PythonAnywhere

# ==========================================
# פונקציית עזר לסינון היסטוריה מימות המשיח
# ==========================================
def get_last_val(key):
    """
    ימות המשיח משרשרת את כל ההיסטוריה של המשתנה ל-URL.
    פונקציה זו שולפת רק את הערך האחרון ביותר שנשלח (העדכני ביותר).
    """
    vals = request.values.getlist(key)
    if vals:
        val = vals[-1].strip()
        return val if val else None
    return None

# ==========================================
# 1. מאגר המידע - רשימת המשתתפים לפי הפתקים
# ==========================================
USERS = {
    "1": 'שלוימי מרומ"ש', "2": 'בני', "3": 'ריקי', "4": 'יעל', "5": 'תהילה',
    "6": 'יהודית הוכמן', "7": 'שולמית הוכמן', "8": 'מיכל הוכמן', "9": 'שלוימי קניבסקי',
    "10": 'יהודה קניבסקי', "11": 'הדסה', "12": 'יוסי יערי', "13": 'שלוימי נתיה"מ',
    "14": 'מאיר פ"כ', "15": 'מאיר קצוה"ח', "16": 'שלוימי פ"כ', "17": 'רותי',
    "18": 'חני פ"כ', "19": 'יוסף', "20": 'חיה', "21": 'יאיר', "23": 'חנה',
    "24": 'מיכאל', "25": 'עקיבא', "26": 'יחיאל', "27": 'נעמי', "28": 'בנימין',
    "29": 'יהודה נתיה"מ', "30": 'מאיר קניבסקי', "31": 'קובי הוכמן', "32": 'חני הוכמן',
    "33": 'חני מרומ"ש', "34": 'חני קניבסקי', "35": 'דסי', "36": 'מוישי הוכמן',
    "37": 'מוישי נתיה"מ', "38": 'שוקי קניבסקי'
}

logged_in_users = {}

# ==========================================
# 2. רשימת השאלות למשחק
# ==========================================
QUESTIONS = [
    {
        "text": "איזו חיה נקראת 'מלך החיות'?",
        "options": ["פיל", "נמר", "אריה", "דוב"],
        "correct_answer": "3"
    },
    {
        "text": "איזה צבע נוצר כשמערבבים כחול וצהוב?",
        "options": ["ירוק", "סגול", "כתום", "חום"],
        "correct_answer": "1"
    },
    {
        "text": "כמה זה 5 כפול 5?",
        "options": ["15", "20", "25", "55"],
        "correct_answer": "3"
    }
    # תוכל להוסיף בחזרה את שאר השאלות שלך לכאן
]

# ==========================================
# 3. ניהול מצב המערכת
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
# 4. נתיבי השרת (Routes)
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/yemot', methods=['GET', 'POST'])
def yemot_api():
    # שימוש בפונקציה החדשה שלנו לכל קליטת נתונים
    phone = get_last_val('ApiPhone')
    call_id = get_last_val('ApiCallId') or phone
    user_id_input = get_last_val('UserId')
    
    idx = game_state["question_index"]
    answer_var_name = f"Answer_Q{idx}"
    
    # 1. מנסים לקלוט את הלחיצה הישירה מהשאלה
    answer_input = get_last_val(answer_var_name)
    
    # 2. מנגנון לכידה מוקדמת חכם ומוגן: מחפש לחיצה רק בהמתנה של השלב שהסתיים הרגע!
    if not answer_input:
        if idx == 0:
            answer_input = get_last_val('WaitLobby')
        else:
            answer_input = get_last_val(f'WaitRev_{idx-1}')

    if not phone:
        phone = "0000000"
        call_id = "0000000"

    # שלב א': זיהוי משתתף
    if call_id not in logged_in_users:
        if user_id_input:
            if user_id_input in USERS:
                logged_in_users[call_id] = user_id_input
                user_name = USERS[user_id_input]
                game_state["connected_players"][user_id_input] = user_name

                if user_id_input not in game_state["global_scores"]:
                    game_state["global_scores"][user_id_input] = {"name": user_name, "score": 0, "time": 0.0}

                clean_name = user_name.replace('"', '')
                return f"read=t-{clean_name} נרשמת בהצלחה אנא המתן לתחילת המשחק=WaitLobby,no,1,1,5,No,No,1"
            else:
                return "read=t-מספר שגוי נסה שוב=UserId,no,2,1,10,No"
        else:
            return "read=t-ברוכים הבאים למשחק הטריויה נא להקיש מספר משתתף וסולמית=UserId,no,2,1,10,No"

    participant_id = logged_in_users[call_id]
    
    # טיפול במצבי המתנה והשהיה
    if game_state["status"] == "lobby":
        return "read=t-אנא המתן לתחילת המשחק=WaitLobby,no,1,1,5,No,No,1"
        
    if game_state["status"] == "pause":
        return "read=t-המשחק מושהה אנא המתן=WaitPause,no,1,1,5,No,No,1"

    if game_state["status"] == "active":
        if participant_id not in game_state["answers"]:
            # מוודאים שהתשובה חוקית (מסננים כל לחיצה אקראית אחרת)
            if answer_input and answer_input in ["1", "2", "3", "4"]: 
                if len(QUESTIONS) > game_state["question_index"]:
                    time_taken = time.time() - game_state["start_time"]
                    current_q = QUESTIONS[game_state["question_index"]]
                    is_correct = (answer_input == current_q.get("correct_answer", ""))

                    game_state["answers"][participant_id] = {
                        "name": USERS[participant_id], "time": time_taken,
                        "correct": is_correct, "choice": answer_input
                    }
                return f"read=t-תשובתך התקבלה אנא המתן=WaitAns_{idx},no,1,1,5,No,No,1"
            else:
                return f"read=t-הקש את מספר התשובה={answer_var_name},no,1,1,8,No"
        else:
            return f"read=t-כבר ענית על השאלה=WaitAns_{idx},no,1,1,5,No,No,1"

    # שלב חשיפת התשובות או סיום המשחק
    return f"read=t-ההצבעה נסגרה אנא המתן=WaitRev_{idx},no,1,1,5,No,No,1"


@app.route('/display', methods=['GET'])
def display():
    return jsonify({
        "status": game_state["status"],
        "question": QUESTIONS[game_state["question_index"]] if len(QUESTIONS) > game_state["question_index"] else None,
        "answers": game_state["answers"],
        "connected_players": game_state["connected_players"],
        "global_scores": game_state["global_scores"],
        "question_index": game_state["question_index"]
    })

# ==========================================
# פקודות ניהול (מקלדת / כפתורים)
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

    return jsonify({"success": True})

@app.route('/api/admin/prev', methods=['POST'])
def prev_question():
    if game_state["question_index"] > 0:
        game_state["question_index"] -= 1
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
        game_state["answers"] = {}
    return jsonify({"success": True})

@app.route('/api/admin/pause', methods=['POST'])
def toggle_pause():
    if game_state["status"] == "active" or game_state["status"] == "reveal":
        game_state["status"] = "pause"
    elif game_state["status"] == "pause":
        game_state["status"] = "active"
        game_state["start_time"] = time.time()
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)