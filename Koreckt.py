import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
import threading
import time
import random
from datetime import datetime
import json
import os

# ==================== НАСТРОЙКИ ====================
API_ID = 34701116
API_HASH = 'd481bf8b670a865da717155f6af892c2'
BOT_TOKEN = '8600586993:AAGyDp9AXOj5Qvl7Q52D68gDiuUbxLDwKLA'
ADMIN_ID = 2097475960

CHATS_FILE = "target_chats.json"
SESSION_FILE = "kor_session.session"

def load_chats():
    try:
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_chats(chats):
    with open(CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(chats, f, ensure_ascii=False, indent=2)

TARGET_CHATS = load_chats()

CONFIG = {
    "mailing_enabled": False,
    "stats": {
        "total_sent": 0,
        "today_sent": 0,
        "errors": 0,
        "last_date": datetime.now().date().isoformat()
    },
    "delay_between_chats": {"min": 150, "max": 400},
    "delay_between_rounds": {"min": 300, "max": 600}
}

bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None
temp_media = {}

# ==================== БАЗА ДАННЫХ ====================
class SimpleDB:
    def __init__(self, filename="koreckt_data.json"):
        self.filename = filename
        self.data = self.load()
    
    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"ads": [], "history": [], "next_id": 1}
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_ad(self, ad_type, text="", media_files=None):
        ad_id = self.data["next_id"]
        self.data["next_id"] += 1
        self.data["ads"].append({
            "id": ad_id, "type": ad_type, "text": text,
            "media_files": media_files or [], "created": datetime.now().isoformat()
        })
        self.save()
        return ad_id
    
    def get_ads(self):
        return self.data["ads"]
    
    def get_ad_by_id(self, ad_id):
        for ad in self.data["ads"]:
            if ad["id"] == ad_id:
                return ad
        return None
    
    def delete_ad(self, ad_id):
        self.data["ads"] = [a for a in self.data["ads"] if a["id"] != ad_id]
        self.save()
    
    def clear_all(self):
        self.data["ads"] = []
        self.save()
    
    def add_history(self, ad_id, chat, success):
        self.data["history"].append({
            "ad_id": ad_id, "chat": chat, "success": success,
            "time": datetime.now().isoformat()
        })
        if len(self.data["history"]) > 1000:
            self.data["history"] = self.data["history"][-1000:]
        self.save()

db = SimpleDB()

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

def send_message(chat, text, photo=None):
    try:
        if photo:
            client.send_file(chat, photo, caption=text)
        else:
            time.sleep(random.uniform(2, 5))
            client.send_message(chat, text)
        return True
    except FloodWaitError as e:
        time.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def mailing_loop():
    global client
    while True:
        if not CONFIG["mailing_enabled"] or not client:
            time.sleep(2)
            continue
        
        ads = db.get_ads()
        if not ads or not TARGET_CHATS:
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        print(f"Round: {ad.get('text', '')[:50]}")
        
        for chat in TARGET_CHATS:
            if not CONFIG["mailing_enabled"]:
                break
            
            success = send_message(chat, ad.get("text", ""), ad.get("media_files", [None])[0] if ad.get("media_files") else None)
            update_stats(success)
            db.add_history(ad["id"], chat, success)
            
            delay = random.uniform(CONFIG["delay_between_chats"]["min"], CONFIG["delay_between_chats"]["max"])
            time.sleep(delay)
        
        time.sleep(random.uniform(CONFIG["delay_between_rounds"]["min"], CONFIG["delay_between_rounds"]["max"]))

# ==================== ЗАГРУЗКА СЕССИИ ЧЕРЕЗ БОТА ====================
@bot.message_handler(commands=['upload_session'])
def upload_session_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    bot.reply_to(msg, "📁 **Отправьте файл kor_session.session**\n\n(как документ, НЕ как фото)")

@bot.message_handler(content_types=['document'])
def handle_session_file(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if msg.document.file_name == "kor_session.session":
        bot.reply_to(msg, "⏳ Загружаю файл сессии...")
        
        file_info = bot.get_file(msg.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open(SESSION_FILE, "wb") as f:
            f.write(downloaded_file)
        
        # Проверяем файл
        if os.path.exists(SESSION_FILE):
            size = os.path.getsize(SESSION_FILE)
            bot.reply_to(msg, f"✅ **Сессия загружена!**\n\n📁 Файл: {SESSION_FILE}\n📦 Размер: {size} байт\n\n🚀 Теперь можно запускать рассылку: /startmail")
            
            # Подключаем клиент
            global client
            try:
                client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
                client.connect()
                if client.is_user_authorized():
                    me = client.get_me()
                    bot.reply_to(msg, f"✅ **Клиент подключён!**\n\n👤 Аккаунт: {me.first_name}")
                else:
                    bot.reply_to(msg, "❌ Файл сессии не валидный")
            except Exception as e:
                bot.reply_to(msg, f"❌ Ошибка подключения: {e}")
        else:
            bot.reply_to(msg, "❌ Ошибка сохранения файла")
    else:
        bot.reply_to(msg, f"❌ Неверный файл. Нужно: kor_session.session\nПолучен: {msg.document.file_name}")

@bot.message_handler(commands=['session_status'])
def session_status(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if os.path.exists(SESSION_FILE):
        size = os.path.getsize(SESSION_FILE)
        bot.reply_to(msg, f"✅ **Сессия есть**\n📁 {SESSION_FILE}\n📦 {size} байт")
    else:
        bot.reply_to(msg, f"❌ **Нет сессии**\n\nОтправьте файл через /upload_session")

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "Доступ запрещён")
        return
    
    session_exists = os.path.exists(SESSION_FILE)
    status = "✅" if CONFIG["mailing_enabled"] else "❌"
    
    info = f"""🤖 **KORECKT БОТ**

📁 Сессия: {'✅ есть' if session_exists else '❌ нет'}
🚀 Рассылка: {status}
📝 Объявлений: {len(db.get_ads())}
🎯 Чатов: {len(TARGET_CHATS)}
📨 Сегодня: {CONFIG['stats']['today_sent']}
📈 Всего: {CONFIG['stats']['total_sent']}

━━━━━━━━━━━━━━━━━━━

📁 **СЕССИЯ:**
/upload_session - загрузить файл сессии
/session_status - проверить сессию

📝 **ОБЪЯВЛЕНИЯ:**
/add [текст] - текстовое
/add_photo - фото + текст
/list - список
/del [ID] - удалить

🎯 **ЧАТЫ:**
/addchat [ссылка] - добавить
/removechat [номер] - удалить
/listchats - список

🚀 **ЗАПУСК:**
/startmail - запустить
/stopmail - остановить

⚙️ **НАСТРОЙКИ:**
/setdelay 150 400 - пауза
/stats - статистика
/check - проверить аккаунт"""
    
    bot.reply_to(msg, info, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_text(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add Текст объявления")
        return
    ad_id = db.add_ad("text", text)
    bot.reply_to(msg, f"✅ Объявление #{ad_id} добавлено")

@bot.message_handler(commands=['add_photo'])
def add_photo(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    temp_media[msg.chat.id] = {"step": "photo"}
    bot.reply_to(msg, "📸 Отправьте ФОТО, затем ТЕКСТ (или /skip)")

@bot.message_handler(commands=['skip'])
def skip_text(msg):
    if msg.chat.id not in temp_media:
        return
    if "photo" in temp_media[msg.chat.id]:
        data = temp_media[msg.chat.id]
        ad_id = db.add_ad("photo", "", [data["photo"]])
        bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото без текста)")
    del temp_media[msg.chat.id]

@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    if msg.chat.id not in temp_media:
        return
    photo = msg.photo[-1].file_id
    temp_media[msg.chat.id] = {"step": "text", "photo": photo}
    bot.reply_to(msg, "📝 Отправьте ТЕКСТ (или /skip)")

@bot.message_handler(func=lambda m: m.chat.id in temp_media and temp_media[m.chat.id].get("step") == "text")
def handle_text(msg):
    data = temp_media[msg.chat.id]
    ad_id = db.add_ad("photo", msg.text, [data["photo"]])
    bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото + текст)")
    del temp_media[msg.chat.id]

@bot.message_handler(commands=['list'])
def list_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "Нет объявлений")
        return
    response = "📝 ОБЪЯВЛЕНИЯ:\n\n"
    for ad in ads[-10:]:
        response += f"ID {ad['id']} [{ad['type']}]: {ad.get('text', '')[:40]}\n"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['del'])
def del_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        db.delete_ad(ad_id)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
    except:
        bot.reply_to(msg, "❌ /del 1")

@bot.message_handler(commands=['addchat'])
def add_chat(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.replace('/addchat', '').strip().split()
    if not parts:
        bot.reply_to(msg, "❌ /addchat https://t.me/chat")
        return
    chat = parts[0]
    if not chat.startswith("https://t.me/"):
        chat = "https://t.me/" + chat.replace("@", "")
    if chat not in TARGET_CHATS:
        TARGET_CHATS.append(chat)
        save_chats(TARGET_CHATS)
        bot.reply_to(msg, f"✅ Чат добавлен: {chat}")
    else:
        bot.reply_to(msg, "⚠️ Чат уже есть")

@bot.message_handler(commands=['removechat'])
def remove_chat(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.replace('/removechat', '').strip().split()
    if not parts:
        bot.reply_to(msg, "❌ /removechat 1")
        return
    if parts[0].isdigit():
        idx = int(parts[0]) - 1
        if 0 <= idx < len(TARGET_CHATS):
            removed = TARGET_CHATS.pop(idx)
            save_chats(TARGET_CHATS)
            bot.reply_to(msg, f"✅ Удалено: {removed}")
        else:
            bot.reply_to(msg, "❌ Неверный номер")
    else:
        chat = parts[0]
        if chat in TARGET_CHATS:
            TARGET_CHATS.remove(chat)
            save_chats(TARGET_CHATS)
            bot.reply_to(msg, f"✅ Удалено: {chat}")

@bot.message_handler(commands=['listchats'])
def list_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not TARGET_CHATS:
        bot.reply_to(msg, "Нет чатов")
        return
    response = "🎯 ЧАТЫ:\n\n"
    for i, chat in enumerate(TARGET_CHATS[:30], 1):
        short = chat.replace("https://t.me/", "@")
        response += f"{i}. {short}\n"
    if len(TARGET_CHATS) > 30:
        response += f"\n...и ещё {len(TARGET_CHATS)-30}"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not os.path.exists(SESSION_FILE):
        bot.reply_to(msg, "❌ Нет сессии! Используйте /upload_session")
        return
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений! /add")
        return
    if len(TARGET_CHATS) == 0:
        bot.reply_to(msg, "❌ Нет чатов! /addchat")
        return
    
    # Подключаем клиент если ещё нет
    global client
    if not client or not client.is_connected():
        try:
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
            client.connect()
            if not client.is_user_authorized():
                bot.reply_to(msg, "❌ Сессия не валидна! Загрузите новую")
                return
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {e}")
            return
    
    CONFIG["mailing_enabled"] = True
    bot.reply_to(msg, "🚀 **РАССЫЛКА ЗАПУЩЕНА!**\n/stopmail - остановить")

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    CONFIG["mailing_enabled"] = False
    bot.reply_to(msg, "🛑 **РАССЫЛКА ОСТАНОВЛЕНА**")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        CONFIG["delay_between_chats"]["min"] = int(parts[0])
        CONFIG["delay_between_chats"]["max"] = int(parts[1])
        bot.reply_to(msg, f"✅ Пауза: {CONFIG['delay_between_chats']['min']}-{CONFIG['delay_between_chats']['max']} сек")
    except:
        bot.reply_to(msg, "❌ /setdelay 150 400")

@bot.message_handler(commands=['stats'])
def show_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    info = f"""📊 **СТАТИСТИКА**

📨 Всего отправлено: {CONFIG['stats']['total_sent']}
❌ Ошибок: {CONFIG['stats']['errors']}
📅 Сегодня: {CONFIG['stats']['today_sent']}
🎯 Чатов: {len(TARGET_CHATS)}
📝 Объявлений: {len(db.get_ads())}

🚀 Статус: {'✅ Активна' if CONFIG['mailing_enabled'] else '❌ Остановлена'}"""
    bot.reply_to(msg, info, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def check_account(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not client or not client.is_connected():
        bot.reply_to(msg, "❌ Клиент не подключён\nЗагрузите сессию через /upload_session")
        return
    try:
        me = client.get_me()
        bot.reply_to(msg, f"✅ **Аккаунт:**\n\n👤 {me.first_name}\n🆔 ID: {me.id}\n📱 Premium: {'Да' if me.premium else 'Нет'}\n\nСтатус: OK")
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {e}")

# ==================== FLASK ДЛЯ RENDER ====================
def start_flask():
    try:
        from flask import Flask
        app = Flask(__name__)
        @app.route('/')
        def home():
            return "KORECKT Bot is running!"
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
    except:
        pass

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("=" * 50)
    print("KORECKT BOT STARTING")
    print("=" * 50)
    
    # Запуск движка
    mailing_thread = threading.Thread(target=mailing_loop, daemon=True)
    mailing_thread.start()
    
    # Запуск Flask
    threading.Thread(target=start_flask, daemon=True).start()
    
    print("Бот запущен!")
    print("Отправь /upload_session и загрузи файл kor_session.session")
    
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
