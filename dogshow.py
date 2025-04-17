from flask import Flask, request
import requests
import sqlite3
import re

app = Flask(__name__)

PAGE_ACCESS_TOKEN = 'EAAGzfzg0bnIBO7HP6ter4AszEbFZAISPIc2jta6pOhZAQbsWy6wfvjF72qV58kZCRdtQMKj3Un1fKJ8bgZAKoCdtgR6JVT43g8sTF8FoAGg0lyn7mFZBjl7u0j9J5HdO4DIX9yGbyqMugFCi7nobOo5SUcCBjcUNiRkZANqFe0yiemlWIWnZBrWQZCwPPiUeHSDCkwZDZD'
VERIFY_TOKEN = 'dogshow'
ADMINS = {"ADMIN_FACEBOOK_ID"}  # Replace with real Facebook ID(s)

conn = sqlite3.connect("dogshow.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, points INTEGER DEFAULT 0, name TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS uploads (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT, attachment_id TEXT, type TEXT)")
conn.commit()

user_states = {}
user_temp_files = {}

def call_send_api(data):
    response = requests.post(
        f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}",
        headers={"Content-Type": "application/json"},
        json=data
    )
    if not response.ok:
        print("SEND ERROR:", response.text)

def send_message(recipient_id, text, quick_replies=None):
    message = {"text": text}
    if quick_replies:
        message["quick_replies"] = quick_replies
    call_send_api({"recipient": {"id": recipient_id}, "message": message})

def send_button_message(recipient_id, text, buttons):
    call_send_api({
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": buttons
                }
            }
        }
    })

def quick_reply(title, payload):
    return {"content_type": "text", "title": title, "payload": payload}

def cancel_reply():
    return quick_reply("❌ Cancel", "CANCEL")

def send_main_menu(user_id):
    send_message(user_id, "Main Menu:", quick_replies=[
        quick_reply("🔎 Search", "SEARCH"),
        quick_reply("📃 List", "LIST"),
        quick_reply("📤 Upload", "UPLOAD"),
        quick_reply("💰 Balance", "BALANCE")
    ])

def is_like(message):
    return message.get("quick_reply") is None and message.get("sticker_id") == 369239263222822

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Invalid verify token", 403

    data = request.get_json()
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event["sender"]["id"]
            if "postback" in event:
                handle_postback(sender_id, event["postback"]["payload"])
            elif "message" in event:
                handle_message(sender_id, event["message"])
    return "ok", 200

def handle_postback(user_id, payload):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    if payload == "GET_STARTED":
        call_send_api({
            "recipient": {"id": user_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": "Hello, bahug kiffy/deck Welcome to Dogshow World!",
                                "image_url": "https://i.postimg.cc/4dcC2xvG/Untitled1.png",
                                "subtitle": "Ito yung nangdogshow ka at feeling mo ang taas mo na ih talagang sumakses ka ih.",
                                "buttons": [
                                    {
                                        "type": "postback",
                                        "title": "✅ Proceed",
                                        "payload": "PROCEED"
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        })
    elif payload == "PROCEED":
        send_main_menu(user_id)

def handle_message(user_id, message):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    if message.get("attachments"):
        if user_states.get(user_id) == "AWAITING_UPLOAD_FILE":
            attachment = message["attachments"][0]
            handle_file_upload(user_id, attachment)
        return

    if is_like(message):
        send_message(user_id, "Invalid command. Please use the main menu.")
        send_main_menu(user_id)
        return

    if message.get("text"):
        text = message["text"].strip()

        if user_id in ADMINS:
            if text.startswith("/"):
                handle_admin_command(user_id, text)
                return

        if text.startswith("/deleteupload "):
            name = text[len("/deleteupload "):].strip()
            if not name:
                send_message(user_id, "Usage: /deleteupload {uploadname}")
                return
            if user_id in ADMINS:
                cur.execute("DELETE FROM uploads WHERE name = ?", (name,))
                conn.commit()
                send_message(user_id, f"Deleted upload '{name}' if it existed.")
            else:
                cur.execute("DELETE FROM uploads WHERE name = ? AND user_id = ?", (name, user_id))
                conn.commit()
                send_message(user_id, f"Deleted your upload '{name}' if it existed.")
            return

        if text == "❌ Cancel":
            user_states.pop(user_id, None)
            user_temp_files.pop(user_id, None)
            send_message(user_id, "Cancelled.")
            send_main_menu(user_id)
            return

        state = user_states.get(user_id)

        if state == "AWAITING_UPLOAD_FILE":
            send_message(user_id, "Please send your file not a text.")
            return

        if state == "AWAITING_UPLOAD_NAME":
            if re.search(r'[\U00010000-\U0010ffff]', text):
                send_message(user_id, "Please enter a name without emoji.")
                return
            save_uploaded_file(user_id, text)
            return

        if state == "AWAITING_SEARCH":
            if re.search(r'[\U00010000-\U0010ffff]', text):
                send_message(user_id, "Please enter a valid search word (not emoji).")
                return
            search_file(user_id, text)
            return

        handle_command(user_id, text)

def handle_admin_command(user_id, text):
    if text.startswith("/deleteupload "):
        name = text[len("/deleteupload "):].strip()
        if not name:
            send_message(user_id, "Usage: /deleteupload {uploadname}")
            return
        cur.execute("DELETE FROM uploads WHERE name = ?", (name,))
        conn.commit()
        send_message(user_id, f"Deleted upload '{name}' if it existed.")
        return

    if text.startswith("/setpoints "):
        parts = text[len("/setpoints "):].strip().split()
        if len(parts) != 2:
            send_message(user_id, "Usage: /setpoints {username} {points}")
            return
        target_name, points_str = parts
        if not points_str.isdigit():
            send_message(user_id, "Points must be a number.")
            return
        points = int(points_str)
        cur.execute("SELECT user_id FROM users WHERE name LIKE ?", (f"%{target_name}%",))
        row = cur.fetchone()
        if row:
            target_id = row[0]
            cur.execute("UPDATE users SET points = ? WHERE user_id = ?", (points, target_id))
            conn.commit()
            send_message(user_id, f"Set points for {target_name} to {points}.")
        else:
            send_message(user_id, f"No user found with name '{target_name}'.")
        return

    send_message(user_id, "Unknown admin command.")

def handle_file_upload(user_id, attachment):
    payload = attachment.get("payload", {})
    attachment_id = payload.get("attachment_id")
    file_type = attachment["type"]

    if not attachment_id and "url" in payload:
        upload_resp = requests.post(
            f"https://graph.facebook.com/v18.0/me/message_attachments?access_token={PAGE_ACCESS_TOKEN}",
            headers={"Content-Type": "application/json"},
            json={
                "message": {
                    "attachment": {
                        "type": file_type,
                        "payload": {
                            "is_reusable": True,
                            "url": payload["url"]
                        }
                    }
                }
            }
        )
        if upload_resp.ok:
            attachment_id = upload_resp.json()["attachment_id"]
        else:
            print("UPLOAD TO FB ERROR:", upload_resp.text)
            send_message(user_id, "Upload failed. Try again with a different file.")
            return

    if not attachment_id:
        send_message(user_id, "Upload failed. Try again with a different file.")
        return

    user_temp_files[user_id] = {"attachment_id": attachment_id, "type": file_type}
    user_states[user_id] = "AWAITING_UPLOAD_NAME"
    send_message(user_id, "Please enter a name for your upload (no emoji):", quick_replies=[cancel_reply()])

def save_uploaded_file(user_id, name):
    file_info = user_temp_files.get(user_id)
    if not file_info:
        send_message(user_id, "No file found.")
        send_main_menu(user_id)
        return

    cur.execute("INSERT INTO uploads (user_id, name, attachment_id, type) VALUES (?, ?, ?, ?)",
                (user_id, name, file_info["attachment_id"], file_info["type"]))
    cur.execute("UPDATE users SET points = points + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

    send_message(user_id, f"Uploaded '{name}' successfully. You earned 1 point!")
    user_temp_files.pop(user_id, None)
    user_states.pop(user_id, None)
    send_main_menu(user_id)

def handle_command(user_id, text):
    if text == "📤 Upload":
        user_states[user_id] = "AWAITING_UPLOAD_FILE"
        send_message(user_id, "Please send your file now (photo, video, audio, or document).", quick_replies=[cancel_reply()])
    elif text == "🔎 Search":
        user_states[user_id] = "AWAITING_SEARCH"
        send_message(user_id, "Enter what you're looking for:", quick_replies=[cancel_reply()])
    elif text == "📃 List":
        cur.execute("SELECT name FROM uploads")
        items = cur.fetchall()
        if items:
            send_message(user_id, "Available uploads:\n" + "\n".join([i[0] for i in items]))
        else:
            send_message(user_id, "No uploads yet.")
        send_main_menu(user_id)
    elif text == "💰 Balance":
        cur.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        points = row[0] if row else 0
        send_message(user_id, f"Your balance: {points} point(s)")
        send_main_menu(user_id)
    else:
        send_message(user_id, "Invalid command. Please use the main menu.")
        send_main_menu(user_id)

def search_file(user_id, query):
    cur.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    points = row[0] if row else 0

    if points < 1:
        send_message(user_id, "Not enough points. Upload first.")
        send_main_menu(user_id)
        return

    cur.execute("SELECT name, type, attachment_id FROM uploads WHERE name LIKE ?", (f"%{query}%",))
    results = cur.fetchall()

    if results:
        cur.execute("UPDATE users SET points = points - 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        for name, file_type, attachment_id in results:
            send_media(user_id, file_type, attachment_id, name)
    else:
        send_message(user_id, "No matches found.")

    user_states.pop(user_id, None)
    send_main_menu(user_id)

def send_media(user_id, media_type, attachment_id, caption):
    call_send_api({
        "recipient": {"id": user_id},
        "message": {
            "attachment": {
                "type": media_type,
                "payload": {
                    "attachment_id": attachment_id
                }
            }
        }
    })
    send_message(user_id, caption)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=2500)