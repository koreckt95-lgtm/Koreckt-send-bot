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

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")

# Flask для Render
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "KORECKT BOT RUNNING", 200

# Конфиг
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

# Простая БД на JSON с блокировкой
db_lock = threading.Lock()

def load_db():
    with db_lock:
        try:
            with open("koreckt.json", "r") as f:
                return json.load(f)
        except:
            return {"ads": [], "history": []}

def save_db(data):
    with db_lock:
        with open("koreckt.json", "w") as f:
            json.dump(data, f)

def add_ad(text):
    data = load_db()
    ad_id = len(data["ads"]) + 1
    data["ads"].append({"id": ad_id, "text": text})
    save_db(data)
    return ad_id

def get_ads():
    return load_db()["ads"]

def delete_ad(ad_id):
    data = load_db()
    data["ads"] = [a for a in data["ads"] if a["id"] != ad_id]
    save_db(data)

def clear_ads():
    data = load_db()
    data["ads"] = []
    save_db(data)

def add_history(ad_id, chat, success):
    data = load_db()
    data["history"].append({
        "ad_id": ad_id,
        "chat": chat,
        "success": success,
        "time": datetime.now().isoformat()
    })
    if len(data["history"]) > 1000:
        data["history"] = data["history"][-1000:]
    save_db(data)

def get_history():
    return load_db()["history"]

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
        print(f"⏳ {reason}: {delay:.1f} сек")
    steps = int(delay)
    for i in range(steps):
        if not CONFIG["mailing_enabled"]:
            break
        if i % 30 == 0 and i > 0:
            print(f"   Осталось: {steps - i} сек...")
        time.sleep(1)

def calculate_typing_time(text):
    speed = random.uniform(CONFIG["typing_speed"]["min"], CONFIG["typing_speed"]["max"])
    base_time = len(text) / speed
    punctuation = text.count('.') * 0.25 + text.count(',') * 0.15
    punctuation += text.count('!') * 0.2 + text.count('?') * 0.2
    punctuation += text.count('\n') * 0.5
    words = text.split()
    long_words = sum(1 for w in words if len(w) > 8) * 0.3
    human_factor = random.uniform(0.85, 1.4)
    total = (base_time + punctuation + long_words) * human_factor
    return min(max(total, 2), 20)

def format_message_with_emoji(text):
    emojis = ["🔥", "💎", "⭐", "✅", "🚀", "💪", "🎯", "📢", "💡", "✨"]
    if random.random() < 0.3 and not any(e in text[:2] for e in emojis):
        text = f"{random.choice(emojis)} {text}"
    return text

def pro_sender_engine():
    global client
    print("🚀 KORECKT ENGINE V2.0 ЗАПУЩЕН")
    
    while client is None:
        print("⏳ Ожидание авторизации...")
        time.sleep(5)
    
    print(f"✅ Авторизован: {client.get_me().first_name}")
    
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
        ad_text = format_message_with_emoji(ad["text"]) if CONFIG["smart_delays"] else ad["text"]
        
        print(f"\n📢 НОВЫЙ КРУГ. Объявление #{ad['id']}")
        
        for idx, chat in enumerate(TARGET_CHATS):
            if not CONFIG["mailing_enabled"] or client is None:
                break
            
            print(f"🎯 {chat}")
            smart_delay(3, 8, "Вход в чат")
            
            try:
                typing_time = calculate_typing_time(ad_text)
                client(functions.messages.SetTypingRequest(
                    peer=chat, action=types.SendMessageTypingAction()
                ))
                time.sleep(typing_time)
                client.send_message(chat, ad_text)
                print(f"✅ Отправлено в {chat}")
                update_stats(True)
                add_history(ad["id"], chat, True)
                
                if CONFIG["stats"]["today_sent"] >= 100:
                    print("⚠️ Дневной лимит. Пауза 30 мин")
                    smart_delay(1800, 1800, "Лимит")
                    
            except FloodWaitError as e:
                print(f"⚠️ Flood: {e.seconds} сек")
                time.sleep(e.seconds + 5)
                add_history(ad["id"], chat, False)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                update_stats(False)
                add_history(ad["id"], chat, False)
                smart_delay(30, 60, "Пауза")
            
            if idx < len(TARGET_CHATS) - 1:
                smart_delay(CONFIG["delay_between_chats"]["min"], 
                           CONFIG["delay_between_chats"]["max"], "Пауза")
        
        if CONFIG["mailing_enabled"] and ads:
            wait = random.uniform(CONFIG["delay_between_rounds"]["min"], 
                                  CONFIG["delay_between_rounds"]["max"])
            print(f"💤 Круг завершен. Пауза {wait:.0f} сек")
            smart_delay(wait, wait, "Пауза")

# ========== КОМАНДЫ БОТА ==========

@bot.message_handler(commands=['login'])
def login_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if client:
        bot.reply_to(msg, "Уже авторизован. /logout для выхода")
        return
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 Введите номер телефона:\n+71234567890")

@bot.message_handler(commands=['logout'])
def logout_cmd(msg):
    global client
    if client:
        client.disconnect()
        client = None
    bot.reply_to(msg, "✅ Вы вышли")

@bot.message_handler(commands=['cancel'])
def cancel_cmd(msg):
    if msg.chat.id in auth_sessions:
        del auth_sessions[msg.chat.id]
    bot.reply_to(msg, "❌ Отменено")

@bot.message_handler(func=lambda m: m.chat.id in auth_sessions)
def auth_handler(msg):
    global client
    chat_id = msg.chat.id
    text = msg.text.strip()
    session = auth_sessions[chat_id]
    
    if session["step"] == "phone":
        if not re.match(r'^\+?\d{10,15}$', text):
            bot.reply_to(msg, "❌ Неверный формат. Пример: +71234567890")
            return
        session["phone"] = text
        session["step"] = "code"
        try:
            temp = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
            session["client"] = temp
            temp.connect()
            temp.send_code_request(text)
            bot.reply_to(msg, "📱 Код отправлен! Введите код:")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")
            del auth_sessions[chat_id]
    
    elif session["step"] == "code":
        try:
            temp = session["client"]
            temp.sign_in(session["phone"], text)
            client = temp
            bot.reply_to(msg, f"✅ Вход выполнен! Аккаунт: {client.get_me().first_name}\n\n/startmail для запуска рассылки")
            del auth_sessions[chat_id]
        except Exception as e:
            if "2FA" in str(e) or "password" in str(e).lower():
                session["step"] = "password"
                bot.reply_to(msg, "🔐 Введите пароль 2FA:")
            else:
                bot.reply_to(msg, f"❌ Ошибка: {str(e)[:150]}")
                del auth_sessions[chat_id]
    
    elif session["step"] == "password":
        try:
            temp = session["client"]
            temp.sign_in(password=text)
            client = temp
            bot.reply_to(msg, f"✅ Вход выполнен! Аккаунт: {client.get_me().first_name}\n\n/startmail для запуска рассылки")
            del auth_sessions[chat_id]
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:150]}")
            del auth_sessions[chat_id]

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    status = "✅ Авторизован" if client else "❌ Не авторизован"
    info = f"""
🔐 KORECKT V2.0

Аккаунт: {status}

Команды:
/login - Войти
/logout - Выйти
/add текст - Добавить объявление
/list - Список
/del ID - Удалить
/clear - Очистить всё
/stats - Статистика
/chats - Чаты
/startmail - ЗАПУСК
/stopmail - СТОП

Статус: {'🟢 РАБОТАЕТ' if CONFIG['mailing_enabled'] else '🔴 СТОП'}
Объявлений: {len(get_ads())}
Отправлено сегодня: {CONFIG['stats']['today_sent']}
Всего: {CONFIG['stats']['total_sent']}
    """
    bot.reply_to(msg, info)

@bot.message_handler(commands=['add'])
def add_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "Использование: /add текст")
        return
    ad_id = add_ad(text)
    bot.reply_to(msg, f"✅ Объявление #{ad_id} добавлено")

@bot.message_handler(commands=['list'])
def list_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    ads = get_ads()
    if not ads:
        bot.reply_to(msg, "Нет объявлений")
        return
    resp = "📝 Список:\n"
    for ad in ads[-10:]:
        resp += f"#{ad['id']}: {ad['text'][:50]}...\n"
    bot.reply_to(msg, resp)

@bot.message_handler(commands=['del'])
def del_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        delete_ad(ad_id)
        bot.reply_to(msg, f"✅ #{ad_id} удален")
    except:
        bot.reply_to(msg, "Использование: /del 1")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    clear_ads()
    bot.reply_to(msg, "✅ Все объявления удалены")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    history = get_history()
    success = sum(1 for h in history if h["success"])
    bot.reply_to(msg, f"""
📊 Статистика:
Отправлено сегодня: {CONFIG['stats']['today_sent']}
Всего отправлено: {CONFIG['stats']['total_sent']}
Ошибок: {CONFIG['stats']['errors']}
Успешность: {(success/len(history)*100 if history else 0):.1f}%
    """)

@bot.message_handler(commands=['chats'])
def chats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    resp = "🎯 Целевые чаты:\n"
    for i, c in enumerate(TARGET_CHATS, 1):
        resp += f"{i}. {c}\n"
    bot.reply_to(msg, resp)

@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    if msg.from_user.id != ADMIN_ID: return
    if not client:
        bot.reply_to(msg, "❌ Сначала /login")
        return
    if not get_ads():
        bot.reply_to(msg, "❌ Нет объявлений. /add")
        return
    CONFIG["mailing_enabled"] = True
    bot.reply_to(msg, f"🚀 Рассылка запущена!\nЧатов: {len(TARGET_CHATS)}\nОбъявлений: {len(get_ads())}")

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    if msg.from_user.id != ADMIN_ID: return
    CONFIG["mailing_enabled"] = False
    bot.reply_to(msg, "🛑 Рассылка остановлена")

@bot.message_handler(commands=['config'])
def config_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, f"""
⚙️ Настройки:
Паузы между чатами: {CONFIG['delay_between_chats']['min']}-{CONFIG['delay_between_chats']['max']} сек
Паузы между кругами: {CONFIG['delay_between_rounds']['min']}-{CONFIG['delay_between_rounds']['max']} сек
Скорость печати: {CONFIG['typing_speed']['min']}-{CONFIG['typing_speed']['max']} симв/сек
    """)

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    try:
        parts = msg.text.replace('/setdelay', '').split()
        CONFIG["delay_between_chats"]["min"] = int(parts[0])
        CONFIG["delay_between_chats"]["max"] = int(parts[1])
        bot.reply_to(msg, f"✅ Установлено: {parts[0]}-{parts[1]} сек")
    except:
        bot.reply_to(msg, "❌ /setdelay 150 400")

@bot.message_handler(commands=['setround'])
def set_round(msg):
    try:
        parts = msg.text.replace('/setround', '').split()
        CONFIG["delay_between_rounds"]["min"] = int(parts[0])
        CONFIG["delay_between_rounds"]["max"] = int(parts[1])
        bot.reply_to(msg, f"✅ Установлено: {parts[0]}-{parts[1]} сек")
    except:
        bot.reply_to(msg, "❌ /setround 300 600")

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT V2.0 ДЛЯ RENDER")
    print("=" * 50)
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=pro_sender_engine, daemon=True).start()
    
    print("✅ Бот запущен")
    print(f"👤 ADMIN_ID: {ADMIN_ID}")
    print("📱 Напишите /start в боте")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
