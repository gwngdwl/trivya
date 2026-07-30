import sys
import unittest
import json
from flask_app import app, game_state, logged_in_users, USERS, QUESTIONS

TEST_QUESTIONS = [
    {
        "id": 1,
        "text": "מהי בירת ישראל?",
        "options": ["ירושלים", "תל אביב", "חיפה", "באר שבע"],
        "correct_answer": "1"
    },
    {
        "id": 2,
        "text": "שאלה 2",
        "options": ["א1", "א2", "א3", "א4"],
        "correct_answer": "1"
    },
    {
        "id": 3,
        "text": "שאלה 3",
        "options": ["א1", "א2", "א3", "א4"],
        "correct_answer": "1"
    },
    {
        "id": 4,
        "type": "poll",
        "text": "שאלת סקר בדיקה",
        "options": ["אופציה 1", "אופציה 2", "אופציה 3", "אופציה 4"]
    }
]

class TestYemotTrivia(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        # Set flask_app.QUESTIONS deterministically for tests
        import flask_app
        flask_app.QUESTIONS = [dict(q) for q in TEST_QUESTIONS]
        # Reset game state before each test
        game_state["question_index"] = 0
        game_state["status"] = "lobby"
        game_state["start_time"] = 0
        game_state["answers"] = {}
        game_state["connected_players"] = {}
        game_state["global_scores"] = {}
        logged_in_users.clear()

    def test_json_loading(self):
        self.assertGreater(len(USERS), 0, "Users should be loaded from JSON")
        self.assertGreater(len(QUESTIONS), 0, "Questions should be loaded from JSON")
        self.assertIn("1", USERS)

    def test_yemot_user_registration(self):
        # Initial call without UserId -> prompt for UserId
        res = self.client.get('/yemot?ApiCallId=CALL100&ApiPhone=0501234567')
        self.assertIn('read=t-ברוכים הבאים למשחק הטריויה', res.get_data(as_text=True))
        self.assertIn('UserId', res.get_data(as_text=True))

        # Enter invalid user ID
        res = self.client.get('/yemot?ApiCallId=CALL100&ApiPhone=0501234567&UserId=999')
        self.assertIn('read=t-מספר שגוי נסה שוב', res.get_data(as_text=True))

        # Enter valid user ID (1 = שלוימי מרומ"ש)
        res = self.client.get('/yemot?ApiCallId=CALL100&ApiPhone=0501234567&UserId=1')
        response_text = res.get_data(as_text=True)
        self.assertIn('נרשמת בהצלחה', response_text)
        # Verify sanitization (quotes removed)
        self.assertNotIn('"', response_text)
        self.assertEqual(logged_in_users.get('CALL100'), '1')

    def test_question_answering_and_parameter_isolation(self):
        # Register User 1
        self.client.get('/yemot?ApiCallId=CALL100&UserId=1')

        # Admin starts game -> status: active, question_index: 0
        self.client.post('/api/admin/auto_next')
        self.assertEqual(game_state["status"], "active")

        # User calls in during active state, prompt is Answer_Q0
        res = self.client.get('/yemot?ApiCallId=CALL100')
        self.assertIn('Answer_Q0', res.get_data(as_text=True))
        self.assertIn('שאלה 1', res.get_data(as_text=True))

        # User submits correct answer (1) for Answer_Q0
        res = self.client.get('/yemot?ApiCallId=CALL100&UserId=1&WaitLobby=&Answer_Q0=1')
        self.assertIn('read=t-תשובתך התקבלה אנא המתן=WaitAns_0', res.get_data(as_text=True))
        self.assertIn('1', game_state["answers"])
        self.assertEqual(game_state["answers"]['1']['choice'], '1')
        self.assertTrue(game_state["answers"]['1']['correct'])

        # Admin moves to reveal state
        self.client.post('/api/admin/auto_next')
        self.assertEqual(game_state["status"], "reveal")
        self.assertEqual(game_state["global_scores"]['1']['score'], 1)

        # Admin moves to Question 1 (active state)
        self.client.post('/api/admin/auto_next')
        self.assertEqual(game_state["status"], "active")
        self.assertEqual(game_state["question_index"], 1)

        # CRITICAL TEST: Yemot sends request preserving old URL query params (including Answer_Q0=1)
        # Ensure system DOES NOT automatically accept Answer_Q0=1 as the answer for Answer_Q1!
        res = self.client.get('/yemot?ApiCallId=CALL100&UserId=1&WaitLobby=&Answer_Q0=1&WaitAns_0=')
        self.assertIn('Answer_Q1', res.get_data(as_text=True))
        self.assertIn('שאלה 2', res.get_data(as_text=True))
        self.assertNotIn('1', game_state["answers"])  # User has NOT answered question 1 yet!

        # Now user submits answer 1 for Answer_Q1
        res = self.client.get('/yemot?ApiCallId=CALL100&UserId=1&WaitLobby=&Answer_Q0=1&WaitAns_0=&Answer_Q1=1')
        self.assertIn('read=t-תשובתך התקבלה אנא המתן=WaitAns_1', res.get_data(as_text=True))
        self.assertIn('1', game_state["answers"])
        self.assertEqual(game_state["answers"]['1']['choice'], '1')

    def test_admin_api_endpoints(self):
        # Test display endpoint
        res = self.client.get('/display')
        data = res.get_json()
        self.assertEqual(data["status"], "lobby")
        self.assertEqual(data["total_questions"], len(TEST_QUESTIONS))

        # Test reload endpoint
        res = self.client.post('/api/admin/reload')
        data = res.get_json()
        self.assertTrue(data["success"])
        import flask_app
        flask_app.QUESTIONS = [dict(q) for q in TEST_QUESTIONS]

        # Test reset endpoint
        self.client.get('/yemot?ApiCallId=CALL100&UserId=1')
        res_reset = self.client.post('/api/admin/reset')
        self.assertTrue(res_reset.get_json()["success"])
        self.assertEqual(game_state["status"], "lobby")
        self.assertEqual(len(game_state["connected_players"]), 0)
        self.assertEqual(game_state["question_index"], 0)

    def test_poll_functionality(self):
        # Register User 1
        self.client.get('/yemot?ApiCallId=CALL100&UserId=1')
        
        # Advance to Q3 (the Poll question)
        game_state["question_index"] = 3
        game_state["status"] = "active"
        
        # User calls during active state of poll Q3
        res = self.client.get('/yemot?ApiCallId=CALL100')
        self.assertIn('Answer_Q3', res.get_data(as_text=True))
        self.assertIn('סקר 4', res.get_data(as_text=True))
        self.assertIn('הקש את מספר האופציה הנבחרת', res.get_data(as_text=True))

        # Submit choice 2
        res = self.client.get('/yemot?ApiCallId=CALL100&UserId=1&Answer_Q3=2')
        self.assertIn('read=t-תשובתך התקבלה אנא המתן=WaitAns_3', res.get_data(as_text=True))
        self.assertIn('1', game_state["answers"])
        self.assertEqual(game_state["answers"]['1']['choice'], '2')
        self.assertTrue(game_state["answers"]['1']['is_poll'])

        # Admin moves to reveal state
        self.client.post('/api/admin/auto_next')
        self.assertEqual(game_state["status"], "reveal")
        
        # Poll should not award score points
        self.assertEqual(game_state["global_scores"]['1']['score'], 0)

        # Check reveal Yemot message
        res = self.client.get('/yemot?ApiCallId=CALL100')
        self.assertIn('ההצבעה לסקר נסגרה', res.get_data(as_text=True))

    def test_hangup_cleans_up_call_and_connected_players(self):
        # Register User 1
        self.client.get('/yemot?ApiCallId=CALL100&UserId=1')
        self.assertEqual(logged_in_users.get('CALL100'), '1')
        self.assertIn('1', game_state["connected_players"])

        # Yemot sends hangup=yes on the final request for the call
        res = self.client.get('/yemot?ApiCallId=CALL100&hangup=yes')
        self.assertEqual(res.get_data(as_text=True), "")
        self.assertNotIn('CALL100', logged_in_users)
        self.assertNotIn('1', game_state["connected_players"])

if __name__ == '__main__':
    unittest.main()

