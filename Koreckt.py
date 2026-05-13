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
from flask import Flask, request
import sqlite3  # Добавляем SQLite вместо JSON

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")

CONFIG = {
    "mailing_enabled": False,
    "stats": {
        "total_sent": 0,
        "today_sent": 0,
        "errors": 0,
        "last_date": datetime.now().date().isoformat()
    },
    "delay_between_chats": {"min": 150, "max": 400},
    "delay_between_rounds": {"min": 300, "max": 600},
    "typing_speed": {"min": 5, "max": 12},
    "anti_flood": True,
    "smart_delays": True
}

bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None
auth_sessions = {}

# Flask app for Render
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "KORECKT BOT IS RUNNING!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

# Используем SQLite вместо JSON (решает проблему "database is locked")
class Database:
    def __init__(self, filename="koreckt.db"):
        self.filename = filename
        self.lock = threading.Lock()
        self.init_db()
    
    def init_db(self):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT,
                    created TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER,
                    chat TEXT,
                    success INTEGER,
                    time TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER
                )
            ''')
            conn.commit()
            conn.close()
    
    def add_ad(self, text):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO ads (text, created) VALUES (?, ?)", 
                          (text, datetime.now().isoformat()))
            conn.commit()
            ad_id = cursor.lastrowid
            conn.close()
            return ad_id
    
    def get_ads(self):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT id, text, created FROM ads ORDER BY id")
            rows = cursor.fetchall()
            conn.close()
            return [{"id": row[0], "text": row[1], "created": row[2]} for row in rows]
    
    def get_ad_by_id(self, ad_id):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT id, text, created FROM ads WHERE id = ?", (ad_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {"id": row[0], "text": row[1], "created": row[2]}
            return None
    
    def delete_ad(self, ad_id):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
            conn.commit()
            conn.close()
    
    def clear_all(self):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ads")
            conn.commit()
            conn.close()
    
    def add_history(self, ad_id, chat, success):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO history (ad_id, chat, success, time) VALUES (?, ?, ?, ?)",
                          (ad_id, chat, 1 if success else 0, datetime.now().isoformat()))
            conn.commit()
            conn.close()
    
    def get_history(self, limit=1000):
        with self.lock:
            conn = sqlite3.connect(self.filename, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT ad_id, chat, success, time FROM history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [{"ad_id": row[0], "chat": row[1], "success": bool(row[2]), "time": row[3]} for row in rows]
    
    def get_stats(self):
        return {"total": 0, "errors": 0}  # Заглушка

db = Database()

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

def smart_delay(min_sec, max_sec, reason=""):
    delay = random.uniform(min_sec, max_sec)
    if reason:
        print(f"Delay {reason}: {delay:.1f} sec")
    steps = int(delay)
    for i in range(steps):
        if not CONFIG["mailing_enabled"]:
            break
        if i % 30 == 0 and i > 0:
            remaining = steps - i
            print(f"Remaining: {remaining} sec")
        time.sleep(1)

def calculate_typing_time(text):
    speed = random.uniform(CONFIG["typing_speed"]["min"], CONFIG["typing_speed"]["max"])
    base_time = len(text) / speed
    punctuation = text.count('.') * 0.25 + text.count(',') * 0.15 + text.count('!') * 0.2 + text.count('?') * 0.2
    punctuation += text.count('\n') * 0.5
    words = text.split()
    long_words = sum(1 for w in words if len(w) > 8)
    long_words_bonus = long_words * 0.3
    human_factor = random.uniform(0.85, 1.4)
    total = (base_time + punctuation + long_words_bonus) * human_factor
    return min(max(total, 2), 20)

def format_message_with_emoji(text):
    emojis = ["🔥", "💎", "⭐", "✅", "🚀", "💪", "🎯", "📢", "💡", "✨"]
    if random.random() < 0.3 and not any(e in text[:2] for e in emojis):
        emoji = random.choice(emojis)
        text = f"{emoji} {text}"
    return text

def pro_sender_engine():
    global client
    print("KORECKT ENGINE V2.0 STARTED")
    print("=" * 40)
    
    while client is None:
        print("Waiting for authorization...")
        time.sleep(5)
    
    print("Userbot authorized successfully")
    try:
        print(f"Account: {client.get_me().first_name}")
    except:
        print("Failed to get account info")
    
    print("=" * 40)
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        if client is None:
            print("Client lost, waiting...")
            time.sleep(10)
            continue
        
        ads = db.get_ads()
        if not ads:
            print("No ads, waiting...")
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        ad_text = ad["text"]
        
        if CONFIG["smart_delays"]:
            ad_text = format_message_with_emoji(ad_text)
        
        print(f"\nNEW ROUND STARTED")
        print(f"Ad ID {ad['id']}: {ad_text[:50]}...")
        
        for idx, chat in enumerate(TARGET_CHATS):
            if not CONFIG["mailing_enabled"]:
                break
            if client is None:
                break
            
            print(f"\nProcessing chat: {chat}")
            smart_delay(3, 8, "Entering chat")
            
            try:
                print("Typing...")
                typing_time = calculate_typing_time(ad_text)
                client(functions.messages.SetTypingRequest(
                    peer=chat,
                    action=types.SendMessageTypingAction()
                ))
                
                if CONFIG["smart_delays"] and len(ad_text) > 100:
                    parts = len(ad_text) // 50
                    for i in range(parts):
                        time.sleep(typing_time / parts)
                        if i % 2 == 0:
                            client(functions.messages.SetTypingRequest(
                                peer=chat,
                                action=types.SendMessageTypingAction()
                            ))
                else:
                    time.sleep(typing_time)
                
                client.send_message(chat, ad_text)
                print(f"SUCCESS sent to {chat}")
                update_stats(True)
                db.add_history(ad["id"], chat, True)
                
                if CONFIG["stats"]["today_sent"] >= 100:
                    print("Daily limit reached. Pause 30 min.")
                    smart_delay(1800, 1800, "Daily limit")
                
            except FloodWaitError as e:
                print(f"FLOOD WAIT: {e.seconds} sec")
                time.sleep(e.seconds + 5)
                db.add_history(ad["id"], chat, False)
            except Exception as e:
                print(f"ERROR in {chat}: {e}")
                update_stats(False)
                db.add_history(ad["id"], chat, False)
                smart_delay(30, 60, "Pause after error")
            
            if idx < len(TARGET_CHATS) - 1:
                smart_delay(CONFIG["delay_between_chats"]["min"], CONFIG["delay_between_chats"]["max"], "Pause between chats")
        
        if CONFIG["mailing_enabled"] and ads and client is not None:
            print(f"\nROUND COMPLETED")
            if CONFIG["stats"]["errors"] > 10:
                wait_min, wait_max = 600, 900
            else:
                wait_min, wait_max = CONFIG["delay_between_rounds"]["min"], CONFIG["delay_between_rounds"]["max"]
            smart_delay(wait_min, wait_max, "Pause between rounds")
            if CONFIG["stats"]["errors"] > 0:
                CONFIG["stats"]["errors"] = max(0, CONFIG["stats"]["errors"] - 1)

@bot.message_handler(commands=['login'])
def login_cmd(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "Access denied")
        return
    if client is not None:
        bot.reply_to(message, "Already authorized! Use /logout to exit")
        return
    auth_sessions[message.chat.id] = {"step": "phone", "temp_client": None, "phone": None}
    bot.reply_to(message, "LOGIN TO TELEGRAM ACCOUNT\n\nEnter phone number in international format:\n+71234567890")

@bot.message_handler(commands=['logout'])
def logout_cmd(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "Access denied")
        return
    global client
    if client:
        try:
            client.disconnect()
        except:
            pass
        client = None
    bot.reply_to(message, "Logged out successfully")
@bot.message_handler(commands=['cancel'])
def cancel_auth_cmd(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "Access denied")
        return
    if message.chat.id in auth_sessions:
        if auth_sessions[message.chat.id]["temp_client"]:
            try:
                auth_sessions[message.chat.id]["temp_client"].disconnect()
            except:
                pass
        del auth_sessions[message.chat.id]
    bot.reply_to(message, "Authorization cancelled")

@bot.message_handler(func=lambda message: message.chat.id in auth_sessions)
def handle_auth_steps(message):
    global client
    chat_id = message.chat.id
    text = message.text.strip()
    session = auth_sessions[chat_id]
    
    if session["step"] == "phone":
        if not re.match(r'^\+?\d{10,15}$', text):
            bot.reply_to(message, "Invalid format. Example: +71234567890\nTry again or /cancel")
            return
        session["phone"] = text
        session["step"] = "code"
        try:
            temp_client = TelegramClient(f'temp_session_{chat_id}', API_ID, API_HASH)
            session["temp_client"] = temp_client
            bot.reply_to(message, "Sending verification code...")
            temp_client.connect()
            temp_client.send_code_request(session["phone"])
            bot.reply_to(message, "Verification code sent\n\nEnter code from Telegram (digits only):\nExample: 12345")
        except Exception as e:
            bot.reply_to(message, f"Error: {str(e)[:100]}\nUse /login to try again")
            del auth_sessions[chat_id]
    
    elif session["step"] == "code":
        if not text.isdigit():
            bot.reply_to(message, "Code must contain only digits\nTry again or /cancel")
            return
        try:
            bot.reply_to(message, "Checking code...")
            session["temp_client"].sign_in(session["phone"], text)
            client = session["temp_client"]
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            bot.reply_to(message, f"SUCCESS!\n\nAccount: {username}\nID: {me.id}\n\nNow you can start mailing with /startmail")
            del auth_sessions[chat_id]
        except Exception as e:
            error_msg = str(e)
            if "2FA" in error_msg or "password" in error_msg.lower():
                session["step"] = "password"
                bot.reply_to(message, "2FA REQUIRED\n\nEnter your Telegram password:")
            else:
                bot.reply_to(message, f"Error: {error_msg[:150]}\nUse /login to try again")
                if session["temp_client"]:
                    try:
                        session["temp_client"].disconnect()
                    except:
                        pass
                del auth_sessions[chat_id]
    
    elif session["step"] == "password":
        try:
            bot.reply_to(message, "Checking password...")
            session["temp_client"].sign_in(password=text)
            client = session["temp_client"]
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            bot.reply_to(message, f"SUCCESS!\n\nAccount: {username}\nID: {me.id}\n\nNow you can start mailing with /startmail")
            del auth_sessions[chat_id]
        except Exception as e:
            bot.reply_to(message, f"Error: {str(e)[:150]}\nUse /login to try again")
            if session["temp_client"]:
                try:
                    session["temp_client"].disconnect()
                except:
                    pass
            del auth_sessions[chat_id]

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "Access denied")
        return
    auth_status = "Not authorized"
    if client:
        try:
            me = client.get_me()
            auth_status = f"Authorized as @{me.username or me.first_name}"
        except:
            auth_status = "Session expired"
    info = f"""
KORECKT V2.0 - MAILING BOT

Account status: {auth_status}

Commands:
/login - Login to Telegram account
/logout - Logout from account
/add [text] - Add ad
/list - List ads
/del [ID] - Delete ad
/clear - Clear all
/stats - Statistics
/chats - List target chats
/startmail - START mailing
/stopmail - STOP mailing
/config - Current config
/setdelay [min] [max] - Set delay between chats
/setround [min] [max] - Set delay between rounds

Status: {'ACTIVE' if CONFIG['mailing_enabled'] else 'STOPPED'}
Ads: {len(db.get_ads())}
Sent today: {CONFIG['stats']['today_sent']}
Total sent: {CONFIG['stats']['total_sent']}
Errors: {CONFIG['stats']['errors']}
    """
    bot.send_message(msg.chat.id, info)

@bot.message_handler(commands=['add'])
def add_ad_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "Usage: /add Your ad text")
        return
    ad_id = db.add_ad(text)
    bot.reply_to(msg, f"Ad #{ad_id} added!\nText: {text[:100]}...")

@bot.message_handler(commands=['list'])
def list_ads_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "No ads")
        return
    response = "ADS LIST:\n\n"
    for ad in ads[-10:]:
        preview = ad['text'][:60] + "..." if len(ad['text']) > 60 else ad['text']
        response += f"ID {ad['id']}: {preview}\n\n"
    if len(ads) > 10:
        response += f"...and {len(ads)-10} more"
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['del'])
def del_ad_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        ad = db.get_ad_by_id(ad_id)
        if ad:
            db.delete_ad(ad_id)
            bot.reply_to(msg, f"Ad #{ad_id} deleted")
        else:
            bot.reply_to(msg, f"Ad #{ad_id} not found")
    except:
        bot.reply_to(msg, "Usage: /del 1")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    db.clear_all()
    bot.reply_to(msg, "All ads cleared")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    ads = db.get_ads()
    history = db.get_history()
    success_count = sum(1 for h in history if h["success"])
    response = f"""
STATISTICS

Ads: {len(ads)}
Successful: {success_count}
Failed: {len(history) - success_count}
Success rate: {(success_count/len(history)*100 if history else 0):.1f}%

Today:
Sent: {CONFIG['stats']['today_sent']}
Errors: {CONFIG['stats']['errors']}

Total:
Sent: {CONFIG['stats']['total_sent']}

Last 5:
"""
    last_5 = history[:5] if history else []
    for h in last_5:
        status = "OK" if h["success"] else "FAIL"
        time_str = h["time"][:19].replace("T", " ")
        response += f"\n{status} {time_str} -> {h['chat']}"
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['chats'])
def chats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    response = "TARGET CHATS:\n\n"
    for i, chat in enumerate(TARGET_CHATS, 1):
        response += f"{i}. {chat}\n"
    response += f"\nTotal: {len(TARGET_CHATS)}"
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['startmail'])
def start_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    if client is None:
        bot.reply_to(msg, "Login first! Use /login")
        return
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "No ads! Add with /add")
        return
    if not CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = True
        bot.reply_to(msg, f"MAILING STARTED!\n\nAds: {len(db.get_ads())}\nChats: {len(TARGET_CHATS)}")
        print("Mailing started by admin")
    else:
        bot.reply_to(msg, "Mailing already active")

@bot.message_handler(commands=['stopmail'])
def stop_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    if CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = False
        bot.reply_to(msg, "MAILING STOPPED")
        print("Mailing stopped by admin")
    else:
        bot.reply_to(msg, "Mailing already stopped")

@bot.message_handler(commands=['config'])
def config_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    response = f"""
CONFIGURATION

Delay between chats: {CONFIG['delay_between_chats']['min']}-{CONFIG['delay_between_chats']['max']} sec
Delay between rounds: {CONFIG['delay_between_rounds']['min']}-{CONFIG['delay_between_rounds']['max']} sec
Typing speed: {CONFIG['typing_speed']['min']}-{CONFIG['typing_speed']['max']} chars/sec
Anti-flood: {'ON' if CONFIG['anti_flood'] else 'OFF'}
Smart delays: {'ON' if CONFIG['smart_delays'] else 'OFF'}

Status: {'ACTIVE' if CONFIG['mailing_enabled'] else 'STOPPED'}
    """
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['setdelay'])
def set_delay_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        min_d = int(parts[0])
        max_d = int(parts[1])
        CONFIG["delay_between_chats"]["min"] = min_d
        CONFIG["delay_between_chats"]["max"] = max_d
        bot.reply_to(msg, f"Delay between chats: {min_d}-{max_d} sec")
    except:
        bot.reply_to(msg, "Usage: /setdelay 150 400")

@bot.message_handler(commands=['setround'])
def set_round_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        parts = msg.text.replace('/setround', '').strip().split()
        min_d = int(parts[0])
        max_d = int(parts[1])
        CONFIG["delay_between_rounds"]["min"] = min_d
        CONFIG["delay_between_rounds"]["max"] = max_d
        bot.reply_to(msg, f"Delay between rounds: {min_d}-{max_d} sec")
    except:
        bot.reply_to(msg, "Usage: /setround 300 600")

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("=" * 50)
    print("KORECKT ULTIMATE V2.0 FOR RENDER")
    print("=" * 50)
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Flask server started on port", os.environ.get("PORT", 8080))
    
    # Start mailing engine
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()
    
    print("Bot started and ready!")
    print(f"Admin ID: {ADMIN_ID}")
    print("Open Telegram and send /start")
    print("Use /login to authorize")
    print("=" * 50)
    
    # Start bot polling
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
