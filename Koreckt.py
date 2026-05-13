import telebot
from telethon.sync import TelegramClient
from telethon import functions, types
from telethon.errors import FloodWaitError
import threading
import time
import random
from datetime import datetime
import json
import re
import os
from flask import Flask

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")

# Простой JSON без блокировок
DATA_FILE = "data.json"

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"ads": [], "history": []}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

CONFIG = {
    "mailing_enabled": False,
    "stats": {
        "total_sent": 0,
        "today_sent": 0,
        "errors": 0,
        "last_date": datetime.now().date().isoformat()
    }
}

bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None

# Flask
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "OK", 200

def add_ad(text):
    data = load_data()
    ad_id = len(data["ads"]) + 1
    data["ads"].append({"id": ad_id, "text": text})
    save_data(data)
    return ad_id

def get_ads():
    return load_data()["ads"]

def delete_ad(ad_id):
    data = load_data()
    data["ads"] = [a for a in data["ads"] if a["id"] != ad_id]
    save_data(data)

def clear_ads():
    data = load_data()
    data["ads"] = []
    save_data(data)

def add_history(ad_id, chat, success):
    data = load_data()
    data["history"].append({
        "ad_id": ad_id,
        "chat": chat,
        "success": success,
        "time": datetime.now().isoformat()
    })
    if len(data["history"]) > 500:
        data["history"] = data["history"][-500:]
    save_data(data)

def get_history():
    return load_data()["history"]

def update_stats(sent=True):
    today = datetime.now().date().isoformat()
    if CONFIG["stats"]["last_date"] != today:
        CONFIG["stats"]["today_sent"] = 0
        CONFIG["stats"]["last_date"] = today
    if sent:
        CONFIG["stats"]["total_sent"] += 1
        CONFIG["stats"]["today_sent"] += 1
    else:
        CONFIG["stats"]["errors"] += 1

def pro_sender_engine():
    global client
    print("Engine started, waiting for login...")
    
    while client is None:
        time.sleep(5)
    
    print("Logged in!")
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        if client is None:
            time.sleep(10)
            continue
        
        ads = get_ads()
        if not ads:
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        
        for chat in TARGET_CHATS:
            if not CONFIG["mailing_enabled"]:
                break
            
            try:
                time.sleep(random.randint(150, 400))
                client.send_message(chat, ad["text"])
                print(f"Sent to {chat}")
                update_stats(True)
                add_history(ad["id"], chat, True)
            except Exception as e:
                print(f"Error: {e}")
                update_stats(False)
                add_history(ad["id"], chat, False)
                time.sleep(60)
        
        time.sleep(random.randint(300, 600))

# АВТОРИЗАЦИЯ
auth_data = {}

@bot.message_handler(commands=['login'])
def login_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    auth_data[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "Send your phone number with + (example: +71234567890)")

@bot.message_handler(commands=['logout'])
def logout_cmd(msg):
    global client
    if client:
        client.disconnect()
        client = None
    bot.reply_to(msg, "Logged out")

@bot.message_handler(func=lambda m: m.chat.id in auth_data)
def auth_step(msg):
    global client
    chat_id = msg.chat.id
    text = msg.text.strip()
    step = auth_data[chat_id]["step"]
    
    if step == "phone":
        auth_data[chat_id]["phone"] = text
        auth_data[chat_id]["step"] = "code"
        try:
            temp = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
            auth_data[chat_id]["client"] = temp
            temp.connect()
            temp.send_code_request(text)
            bot.reply_to(msg, "Code sent! Enter the code you received:")
        except Exception as e:
            bot.reply_to(msg, f"Error: {e}")
            del auth_data[chat_id]
    
    elif step == "code":
        try:
            temp = auth_data[chat_id]["client"]
            temp.sign_in(auth_data[chat_id]["phone"], text)
            client = temp
            bot.reply_to(msg, "✅ Login successful! Now use /startmail")
            del auth_data[chat_id]
        except Exception as e:
            if "2FA" in str(e):
                auth_data[chat_id]["step"] = "password"
                bot.reply_to(msg, "Enter your 2FA password:")
            else:
                bot.reply_to(msg, f"Error: {e}")
                del auth_data[chat_id]
    
    elif step == "password":
        try:
            temp = auth_data[chat_id]["client"]
            temp.sign_in(password=text)
            client = temp
            bot.reply_to(msg, "✅ Login successful! Now use /startmail")
            del auth_data[chat_id]
        except Exception as e:
            bot.reply_to(msg, f"Error: {e}")
            del auth_data[chat_id]

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    status = "✅ Authorized" if client else "❌ Not authorized"
    info = f"""
KORECKT BOT

Status: {status}
Mailing: {'ON' if CONFIG['mailing_enabled'] else 'OFF'}
Ads: {len(get_ads())}
Sent today: {CONFIG['stats']['today_sent']}

Commands:
/login - Login to Telegram
/logout - Logout
/add TEXT - Add ad
/list - List ads
/del ID - Delete ad
/clear - Clear all
/stats - Statistics
/startmail - Start mailing
/stopmail - Stop mailing
    """
    bot.reply_to(msg, info)

@bot.message_handler(commands=['add'])
def add_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    text = msg.text.replace('/add', '').strip()
    if text:
        ad_id = add_ad(text)
        bot.reply_to(msg, f"Ad #{ad_id} added")
    else:
        bot.reply_to(msg, "Usage: /add your text")

@bot.message_handler(commands=['list'])
def list_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    ads = get_ads()
    if not ads:
        bot.reply_to(msg, "No ads")
        return
    resp = "Ads:\n"
    for ad in ads[-10:]:
        resp += f"#{ad['id']}: {ad['text'][:50]}...\n"
    bot.reply_to(msg, resp)

@bot.message_handler(commands=['del'])
def del_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        delete_ad(ad_id)
        bot.reply_to(msg, f"Ad #{ad_id} deleted")
    except:
        bot.reply_to(msg, "Usage: /del 1")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    clear_ads()
    bot.reply_to(msg, "All ads cleared")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    history = get_history()
    success = sum(1 for h in history if h["success"])
    resp = f"""
Total sent: {CONFIG['stats']['total_sent']}
Today sent: {CONFIG['stats']['today_sent']}
Errors: {CONFIG['stats']['errors']}
Success rate: {(success/len(history)*100 if history else 0):.1f}%
    """
    bot.reply_to(msg, resp)

@bot.message_handler(commands=['startmail'])
def start_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    if client is None:
        bot.reply_to(msg, "Login first! Use /login")
        return
    if len(get_ads()) == 0:
        bot.reply_to(msg, "Add ads first! Use /add")
        return
    CONFIG["mailing_enabled"] = True
    bot.reply_to(msg, "Mailing STARTED!")

@bot.message_handler(commands=['stopmail'])
def stop_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    CONFIG["mailing_enabled"] = False
    bot.reply_to(msg, "Mailing STOPPED")

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("Starting KORECKT...")
    
    # Flask thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Engine thread
    threading.Thread(target=pro_sender_engine, daemon=True).start()
    
    print("Bot started!")
    
    # Bot polling
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
