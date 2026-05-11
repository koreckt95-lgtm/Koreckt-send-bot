import telebot
from telethon.sync import TelegramClient
from telethon import functions, types
from telethon.errors import FloodWaitError
import sqlite3
import threading
import time
import random
from datetime import datetime, timedelta
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

# Если чаты не заданы в переменных, используем значение по умолчанию
if not TARGET_CHATS or TARGET_CHATS == ['']:
    TARGET_CHATS = ['@shaika_pridneprovskix']
# ===================================================

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Бот Koreckt работает!"

@app.route('/health')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# Конфигурация
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

# ==================== БАЗА ДАННЫХ ДЛЯ МЕДИА ====================
class MediaDB:
    def __init__(self, filename="koreckt_data.json"):
        self.filename = filename
        self.data = self.load()
    
    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"ads": [], "history": [], "temp_media": []}
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_ad(self, text, media_paths=None, media_type='text'):
        ad_id = len(self.data["ads"]) + 1
        self.data["ads"].append({
            "id": ad_id, 
            "text": text, 
            "media_paths": media_paths or [],
            "media_type": media_type,
            "created": datetime.now().isoformat()
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
        self.data["ads"] = [ad for ad in self.data["ads"] if ad["id"] != ad_id]
        self.save()
    
    def clear_all(self):
        self.data["ads"] = []
        self.save()
    
    def add_history(self, ad_id, chat, success):
        self.data["history"].append({
            "ad_id": ad_id,
            "chat": chat,
            "success": success,
            "time": datetime.now().isoformat()
        })
        if len(self.data["history"]) > 1000:
            self.data["history"] = self.data["history"][-1000:]
        self.save()
    
    def save_temp_media(self, paths, msg_id):
        self.data["temp_media"] = {"paths": paths, "msg_id": msg_id}
        self.save()
    
    def get_temp_media(self):
        return self.data.get("temp_media", {})

db = MediaDB()

# Папка для медиа
MEDIA_DIR = "media_files"
os.makedirs(MEDIA_DIR, exist_ok=True)

def download_media(message):
    """Скачивание фото/видео из сообщения"""
    downloaded = []
    
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            filename = f"{MEDIA_DIR}/photo_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            with open(filename, 'wb') as f:
                f.write(downloaded_file)
            downloaded.append(filename)
            
        elif message.video:
            file_id = message.video.file_id
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            filename = f"{MEDIA_DIR}/video_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.mp4"
            with open(filename, 'wb') as f:
                f.write(downloaded_file)
            downloaded.append(filename)
            
        elif message.document:
            file_id = message.document.file_id
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            ext = os.path.splitext(message.document.file_name)[1] or ".bin"
            filename = f"{MEDIA_DIR}/doc_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
            with open(filename, 'wb') as f:
                f.write(downloaded_file)
            downloaded.append(filename)
            
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
    
    return downloaded

def send_media_to_chat(chat, ad):
    """Отправка медиа в чат через Telethon"""
    global client
    
    media_paths = ad.get("media_paths", [])
    media_type = ad.get("media_type", "text")
    caption = ad.get("text", "") or ""
    
    try:
        if media_type == "text" or not media_paths:
            client.send_message(chat, caption)
            
        elif media_type == "photo" and len(media_paths) == 1:
            with open(media_paths[0], 'rb') as f:
                client.send_file(chat, f, caption=caption)
                
        elif media_type in ["photo", "album"] and len(media_paths) > 1:
            # Отправляем альбом (до 10 фото)
            files = []
            for path in media_paths[:10]:
                if os.path.exists(path):
                    files.append(open(path, 'rb'))
            if files:
                client.send_file(chat, files, caption=caption)
                for f in files:
                    f.close()
                    
        elif media_type == "video":
            with open(media_paths[0], 'rb') as f:
                client.send_file(chat, f, caption=caption)
                
        return True
        
    except Exception as e:
        print(f"Ошибка отправки медиа: {e}")
        return False

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
            remaining = steps - i
            print(f"   Осталось: {remaining} сек...")
        time.sleep(1)

def calculate_typing_time(text):
    if not text:
        return 2
    speed = random.uniform(CONFIG["typing_speed"]["min"], CONFIG["typing_speed"]["max"])
    base_time = len(text) / speed
    punctuation = text.count('.') * 0.25 + text.count(',') * 0.15
    human_factor = random.uniform(0.85, 1.4)
    total = (base_time + punctuation) * human_factor
    return min(max(total, 2), 20)

def format_message_with_emoji(text):
    if not text:
        return text
    emojis = ["🔥", "💎", "⭐", "✅", "🚀", "💪", "🎯", "📢", "💡", "✨"]
    if random.random() < 0.3 and not any(e in text[:2] for e in emojis):
        text = f"{random.choice(emojis)} {text}"
    return text

def pro_sender_engine():
    global client
    
    print("🚀 KORECKT ENGINE ЗАПУЩЕН")
    
    try:
        client = TelegramClient('kor_session', API_ID, API_HASH)
        client.start()
        print("✅ Юзербот авторизован")
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        return
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        ads = db.get_ads()
        if not ads:
            print("📭 База объявлений пуста")
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        ad_text = ad.get("text", "")
        media_type = ad.get("media_type", "text")
        
        if CONFIG["smart_delays"] and ad_text:
            ad_text = format_message_with_emoji(ad_text)
        
        print(f"\n📢 НОВЫЙ КРУГ | ID: {ad['id']} | Тип: {media_type}")
        
        for idx, chat in enumerate(TARGET_CHATS):
            if not CONFIG["mailing_enabled"]:
                break
            
            print(f"\n🎯 Чат: {chat}")
            smart_delay(3, 8, "Имитация входа")
            
            try:
                if ad_text:
                    typing_time = calculate_typing_time(ad_text)
                    client(functions.messages.SetTypingRequest(
                        peer=chat,
                        action=types.SendMessageTypingAction()
                    ))
                    time.sleep(typing_time)
                
                success = send_media_to_chat(chat, ad)
                
                if success:
                    print(f"✅ Отправлено в {chat}")
                    update_stats(True)
                    db.add_history(ad["id"], chat, True)
                else:
                    print(f"❌ Ошибка в {chat}")
                    update_stats(False)
                    db.add_history(ad["id"], chat, False)
                
            except FloodWaitError as e:
                print(f"⚠️ FloodWait: {e.seconds} сек")
                time.sleep(e.seconds)
                db.add_history(ad["id"], chat, False)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                update_stats(False)
                db.add_history(ad["id"], chat, False)
                smart_delay(30, 60, "Пауза после ошибки")
            
            if idx < len(TARGET_CHATS) - 1:
                smart_delay(CONFIG["delay_between_chats"]["min"], 
                          CONFIG["delay_between_chats"]["max"], 
                          "Пауза между чатами")
        
        if CONFIG["mailing_enabled"] and ads:
            print(f"\n💤 КРУГ ЗАВЕРШЕН")
            wait_min = 600 if CONFIG["stats"]["errors"] > 10 else CONFIG["delay_between_rounds"]["min"]
            wait_max = 900 if CONFIG["stats"]["errors"] > 10 else CONFIG["delay_between_rounds"]["max"]
            smart_delay(wait_min, wait_max, "Пауза между кругами")
            
            if CONFIG["stats"]["errors"] > 0:
                CONFIG["stats"]["errors"] = max(0, CONFIG["stats"]["errors"] - 1)

# ==================== КОМАНДЫ БОТА (БЕЗ MARKDOWN) ====================

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    status = "АКТИВНА" if CONFIG["mailing_enabled"] else "ОСТАНОВЛЕНА"
    info = f"""
🔐 KORECKT V2.0 - РАССЫЛЬЩИК

📋 КОМАНДЫ:

📝 ДОБАВЛЕНИЕ:
/add_text [текст] - Только текст
/add_photo - Фото + текст
/add_album - Альбом (до 10 фото)
/add_video - Видео + текст

📊 УПРАВЛЕНИЕ:
/list - Список объявлений
/del [ID] - Удалить
/clear - Очистить всё
/stats - Статистика
/chats - Список чатов

🚀 РАССЫЛКА:
/startmail - ЗАПУСК
/stopmail - ОСТАНОВ

📊 Статус: {status}
📝 Объявлений: {len(db.get_ads())}
✅ Отправлено сегодня: {CONFIG['stats']['today_sent']}
❌ Ошибок: {CONFIG['stats']['errors']}
"""
    bot.send_message(msg.chat.id, info)

@bot.message_handler(commands=['add_text'])
def add_text_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    text = msg.text.replace('/add_text', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add_text Ваше объявление")
        return
    
    ad_id = db.add_ad(text, None, 'text')
    bot.reply_to(msg, f"✅ Текстовое объявление #{ad_id} добавлено")

@bot.message_handler(commands=['add_photo'])
def add_photo_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "📸 Отправьте ФОТО, затем напишите текст (или /skip)")
    db.temp_data = {"step": "waiting_photo", "type": "photo"}

@bot.message_handler(commands=['add_album'])
def add_album_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "📸 Отправляйте ФОТО (до 10 шт), затем /done, потом текст (или /skip)")
    db.album_photos = []
    db.temp_data = {"step": "waiting_album", "type": "album"}

@bot.message_handler(commands=['add_video'])
def add_video_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "🎬 Отправьте ВИДЕО, затем текст (или /skip)")
    db.temp_data = {"step": "waiting_video", "type": "video"}

@bot.message_handler(commands=['list'])
def list_ads_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "📭 База пуста")
        return
    
    response = "📝 СПИСОК ОБЪЯВЛЕНИЙ:\n\n"
    for ad in ads[-15:]:
        emoji = "📝" if ad['media_type'] == 'text' else ("📸" if ad['media_type'] in ['photo', 'album'] else "🎬")
        preview = ad['text'][:50] + "..." if ad['text'] and len(ad['text']) > 50 else (ad['text'] or "без текста")
        response += f"{emoji} ID {ad['id']}: {preview}\n"
    
    if len(ads) > 15:
        response += f"\n...и еще {len(ads)-15} объявлений"
    
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['del'])
def del_ad_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        if db.get_ad_by_id(ad_id):
            db.delete_ad(ad_id)
            bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
        else:
            bot.reply_to(msg, f"❌ ID {ad_id} не найден")
    except:
        bot.reply_to(msg, "❌ /del 1")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    db.clear_all()
    bot.reply_to(msg, "🗑️ База очищена")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    ads = db.get_ads()
    history = db.data["history"]
    success_count = sum(1 for h in history if h["success"])
    
    response = f"""
📊 СТАТИСТИКА

📝 Объявлений: {len(ads)}
✅ Успешно: {success_count}
❌ Ошибок: {len(history) - success_count}
📈 Успешность: {(success_count/len(history)*100 if history else 0):.1f}%

🚀 Сегодня: {CONFIG['stats']['today_sent']}
📬 Всего: {CONFIG['stats']['total_sent']}

Типы контента:
"""
    text_count = sum(1 for ad in ads if ad['media_type'] == 'text')
    photo_count = sum(1 for ad in ads if ad['media_type'] in ['photo', 'album'])
    video_count = sum(1 for ad in ads if ad['media_type'] == 'video')
    response += f"📝 Текст: {text_count}\n📸 Фото/Альбом: {photo_count}\n🎬 Видео: {video_count}"
    
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['chats'])
def chats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    response = "🎯 ЦЕЛЕВЫЕ ЧАТЫ:\n\n"
    for i, chat in enumerate(TARGET_CHATS, 1):
        if chat and chat.strip():
            response += f"{i}. {chat}\n"
    response += f"\nВсего: {len([c for c in TARGET_CHATS if c and c.strip()])} чатов"
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['startmail'])
def start_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "❌ База пуста! Добавьте объявления через /add_text")
        return
    
    if not CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = True
        bot.reply_to(msg, f"🚀 РАССЫЛКА ЗАПУЩЕНА!\n📝 Объявлений: {len(db.get_ads())}\n🎯 Чатов: {len(TARGET_CHATS)}")
    else:
        bot.reply_to(msg, "⚠️ Рассылка уже активна")

@bot.message_handler(commands=['stopmail'])
def stop_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    if CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = False
        bot.reply_to(msg, "🛑 РАССЫЛКА ОСТАНОВЛЕНА")
    else:
        bot.reply_to(msg, "⚠️ Рассылка не активна")

@bot.message_handler(commands=['status'])
def status_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    status = "АКТИВНА" if CONFIG["mailing_enabled"] else "ОСТАНОВЛЕНА"
    response = f"""
Статус: {status}
Объявлений: {len(db.get_ads())}
Отправлено сегодня: {CONFIG['stats']['today_sent']}
Всего отправлено: {CONFIG['stats']['total_sent']}
Ошибок: {CONFIG['stats']['errors']}
Чатов: {len(TARGET_CHATS)}
"""
    bot.send_message(msg.chat.id, response)

# Обработка медиа
@bot.message_handler(content_types=['photo', 'video'])
def handle_media(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    temp = getattr(db, 'temp_data', None)
    if not temp:
        return
    
    step = temp.get("step")
    
    if step == "waiting_photo" and message.photo:
        paths = download_media(message)
        if paths:
            db.temp_data = {"step": "waiting_caption", "media_paths": paths, "type": "photo"}
            bot.reply_to(message, "✅ Фото сохранено! Теперь напишите текст (или /skip)")
    
    elif step == "waiting_video" and message.video:
        paths = download_media(message)
        if paths:
            db.temp_data = {"step": "waiting_caption", "media_paths": paths, "type": "video"}
            bot.reply_to(message, "✅ Видео сохранено! Теперь напишите текст (или /skip)")
    
    elif step == "waiting_album" and message.photo:
        if not hasattr(db, 'album_photos'):
            db.album_photos = []
        
        paths = download_media(message)
        if paths:
            db.album_photos.extend(paths)
            remaining = 10 - len(db.album_photos)
            bot.reply_to(message, f"📸 Фото {len(db.album_photos)}/10. Осталось {remaining} или /done")

@bot.message_handler(content_types=['text'])
def handle_caption(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    temp = getattr(db, 'temp_data', None)
    
    if temp and temp.get("step") == "waiting_caption":
        text = "" if message.text == '/skip' else message.text
        media_type = temp.get("type", "text")
        media_paths = temp.get("media_paths", [])
        
        ad_id = db.add_ad(text, media_paths, media_type)
        bot.reply_to(message, f"✅ Объявление #{ad_id} создано!\nТип: {media_type}\nФайлов: {len(media_paths)}")
        db.temp_data = None
    
    elif message.text == '/done' and hasattr(db, 'album_photos') and db.album_photos:
        bot.reply_to(message, f"✅ Собрано {len(db.album_photos)} фото! Теперь напишите текст (или /skip)")
        db.temp_data = {"step": "waiting_caption", "media_paths": db.album_photos.copy(), "type": "album"}
        db.album_photos = []

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT V3.0 - С ПОДДЕРЖКОЙ ФОТО/ВИДЕО")
    print("=" * 50)
    print(f"🎯 Чаты: {TARGET_CHATS}")
    
    # Запуск веб-сервера
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    
    # Запуск движка рассылки
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()
    
    print("✅ Бот запущен!")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
