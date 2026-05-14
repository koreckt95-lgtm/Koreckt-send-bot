import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
import threading
import time
import random
import json
import os
from datetime import datetime

# ==================== НАСТРОЙКИ ====================
API_ID = 34701116
API_HASH = 'd481bf8b670a865da717155f6af892c2'
BOT_TOKEN = '8600586993:AAGyDp9AXOj5Qvl7Q52D68gDiuUbxLDwKLA'
ADMIN_ID = 2097475960

CHATS_FILE = "chats.json"
ADS_FILE = "ads.json"
SESSION_FILE = "kor_session.session"

# Загрузка чатов
def load_chats():
    try:
        with open(CHATS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_chats(chats):
    with open(CHATS_FILE, 'w') as f:
        json.dump(chats, f)

# Загрузка объявлений
def load_ads():
    try:
        with open(ADS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_ads(ads):
    with open(ADS_FILE, 'w') as f:
        json.dump(ads, f)

# ==================== ГЛОБАЛЬНЫЕ ====================
bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_active = False
auth_sessions = {}
temp_media = {}

# Настройки
delay_min = 150
delay_max = 400
stats = {"sent": 0, "errors": 0, "today": 0, "last_date": datetime.now().date().isoformat()}

# ==================== АВТОРИЗАЦИЯ ====================
@bot.message_handler(commands=['auth'])
def auth_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 **Авторизация**\n\nВведите номер телефона:\n`+380XXXXXXXXX`", parse_mode="Markdown")

@bot.message_handler(commands=['clean'])
def clean_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
        bot.reply_to(msg, "✅ Старая сессия удалена\nТеперь используйте /auth")
    else:
        bot.reply_to(msg, "❌ Файла сессии нет")

@bot.message_handler(commands=['status'])
def status_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if os.path.exists(SESSION_FILE):
        size = os.path.getsize(SESSION_FILE)
        bot.reply_to(msg, f"✅ Сессия есть\n📦 Размер: {size} байт")
    else:
        bot.reply_to(msg, "❌ Нет сессии. Используйте /auth")

@bot.message_handler(func=lambda m: m.chat.id in auth_sessions)
def auth_handler(msg):
    chat_id = msg.chat.id
    step = auth_sessions[chat_id]["step"]
    
    if step == "phone":
        phone = msg.text.strip()
        if not phone.startswith("+"):
            phone = "+" + phone
        
        try:
            temp = TelegramClient(f'temp_{chat_id}', API_ID, API_HASH)
            temp.connect()
            temp.send_code_request(phone)
            auth_sessions[chat_id] = {"step": "code", "phone": phone, "client": temp}
            bot.reply_to(msg, "📱 **Код отправлен!**\n\nВведите код из Telegram:")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")
            
    elif step == "code":
        code = msg.text.strip()
        data = auth_sessions[chat_id]
        
        try:
            data["client"].sign_in(data["phone"], code)
            global client
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
            client.connect()
            client.sign_in(data["phone"], code)
            me = client.get_me()
            del auth_sessions[chat_id]
            bot.reply_to(msg, f"✅ **Авторизация успешна!**\n\n👤 {me.first_name}\n🆔 {me.id}\n\n🚀 Теперь: /startmail")
        except SessionPasswordNeededError:
            auth_sessions[chat_id]["step"] = "password"
            bot.reply_to(msg, "🔐 Введите 2FA пароль:")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")
            
    elif step == "password":
        pwd = msg.text.strip()
        data = auth_sessions[chat_id]
        
        try:
            data["client"].sign_in(password=pwd)
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
            client.connect()
            client.sign_in(password=pwd)
            me = client.get_me()
            del auth_sessions[chat_id]
            bot.reply_to(msg, f"✅ **Авторизация успешна!**\n\n👤 {me.first_name}\n🆔 {me.id}\n\n🚀 Теперь: /startmail")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")

# ==================== ОБЪЯВЛЕНИЯ ====================
@bot.message_handler(commands=['add'])
def add_text(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add Текст объявления")
        return
    
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "text", "text": text})
    save_ads(ads)
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
        ads = load_ads()
        ad_id = len(ads) + 1
        ads.append({"id": ad_id, "type": "photo", "text": "", "photo": data["photo"]})
        save_ads(ads)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото)")
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
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "photo", "text": msg.text, "photo": data["photo"]})
    save_ads(ads)
    del temp_media[msg.chat.id]
    bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото + текст)")

@bot.message_handler(commands=['list'])
def list_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    ads = load_ads()
    if not ads:
        bot.reply_to(msg, "📭 Нет объявлений")
        return
    response = "📝 **Объявления:**\n\n"
    for ad in ads[-10:]:
        response += f"ID {ad['id']} [{ad['type']}]: {ad.get('text', '')[:40]}\n"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['del'])
def del_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        ads = load_ads()
        ads = [a for a in ads if a["id"] != ad_id]
        save_ads(ads)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
    except:
        bot.reply_to(msg, "❌ /del 1")

@bot.message_handler(commands=['clear'])
def clear_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    save_ads([])
    bot.reply_to(msg, "🗑️ Все объявления удалены")

# ==================== ЧАТЫ ====================
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
    chats = load_chats()
    if chat not in chats:
        chats.append(chat)
        save_chats(chats)
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
    chats = load_chats()
    if parts[0].isdigit():
        idx = int(parts[0]) - 1
        if 0 <= idx < len(chats):
            removed = chats.pop(idx)
            save_chats(chats)
            bot.reply_to(msg, f"✅ Удалено: {removed}")
        else:
            bot.reply_to(msg, "❌ Неверный номер")
    else:
        chat = parts[0]
        if chat in chats:
            chats.remove(chat)
            save_chats(chats)
            bot.reply_to(msg, f"✅ Удалено: {chat}")

@bot.message_handler(commands=['listchats'])
def list_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    chats = load_chats()
    if not chats:
        bot.reply_to(msg, "📭 Нет чатов")
        return
    response = "🎯 **Чаты:**\n\n"
    for i, chat in enumerate(chats[:30], 1):
        short = chat.replace("https://t.me/", "@")
        response += f"{i}. {short}\n"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['clearchats'])
def clear_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    save_chats([])
    bot.reply_to(msg, "🗑️ Все чаты удалены")

# ==================== ОТПРАВКА ====================
def send_message(chat, text, photo=None):
    try:
        if photo:
            client.send_file(chat, photo, caption=text)
        else:
            time.sleep(random.uniform(2, 5))
            client.send_message(chat, text)
        return True
    except FloodWaitError as e:
        print(f"Flood: {e.seconds}")
        time.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def mailing_loop():
    global mailing_active, stats
    
    while True:
        if not mailing_active or not client:
            time.sleep(2)
            continue
        
        # Дневной лимит
        today = datetime.now().date().isoformat()
        if stats["last_date"] != today:
            stats["today"] = 0
            stats["last_date"] = today
        
        ads = load_ads()
        chats = load_chats()
        
        if not ads or not chats:
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        print(f"Рассылка: {ad.get('text', '')[:50]}")
        
        for chat in chats:
            if not mailing_active:
                break
            
            photo = ad.get("photo") if ad.get("type") == "photo" else None
            success = send_message(chat, ad.get("text", ""), photo)
            
            if success:
                stats["sent"] += 1
                stats["today"] += 1
                print(f"✅ {chat}")
            else:
                stats["errors"] += 1
                print(f"❌ {chat}")
                time.sleep(60)
            
            time.sleep(random.uniform(delay_min, delay_max))
        
        print("Круг завершён, пауза...")
        time.sleep(random.uniform(300, 600))

# ==================== УПРАВЛЕНИЕ ====================
@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    global mailing_active, client
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not os.path.exists(SESSION_FILE):
        bot.reply_to(msg, "❌ Нет сессии! Используйте /auth")
        return
    
    if not client or not client.is_connected():
        try:
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
            client.connect()
            if not client.is_user_authorized():
                bot.reply_to(msg, "❌ Сессия не валидна! Используйте /auth")
                return
            me = client.get_me()
            bot.reply_to(msg, f"✅ Подключено: {me.first_name}")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {e}")
            return
    
    if len(load_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений! /add")
        return
    
    if len(load_chats()) == 0:
        bot.reply_to(msg, "❌ Нет чатов! /addchat")
        return
    
    mailing_active = True
    bot.reply_to(msg, "🚀 **РАССЫЛКА ЗАПУЩЕНА**")
    threading.Thread(target=mailing_loop, daemon=True).start()

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    global mailing_active
    if msg.from_user.id != ADMIN_ID:
        return
    mailing_active = False
    bot.reply_to(msg, "🛑 **РАССЫЛКА ОСТАНОВЛЕНА**")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    global delay_min, delay_max
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        delay_min = int(parts[0])
        delay_max = int(parts[1])
        bot.reply_to(msg, f"✅ Пауза: {delay_min}-{delay_max} сек")
    except:
        bot.reply_to(msg, "❌ /setdelay 150 400")

@bot.message_handler(commands=['stats'])
def show_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    info = f"""📊 **СТАТИСТИКА**

📨 Всего отправлено: {stats['sent']}
❌ Ошибок: {stats['errors']}
📅 Сегодня: {stats['today']}
🎯 Чатов: {len(load_chats())}
📝 Объявлений: {len(load_ads())}

🚀 Рассылка: {'✅ Активна' if mailing_active else '❌ Остановлена'}"""
    bot.reply_to(msg, info, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def check_account(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not client or not client.is_connected():
        bot.reply_to(msg, "❌ Не авторизован. Используйте /auth")
        return
    try:
        me = client.get_me()
        bot.reply_to(msg, f"✅ **Аккаунт:**\n\n👤 {me.first_name}\n🆔 {me.id}")
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещён")
        return
    
    session_exists = os.path.exists(SESSION_FILE)
    info = f"""🤖 **KORECKT БОТ**

📁 Сессия: {'✅ есть' if session_exists else '❌ нет'}
📝 Объявлений: {len(load_ads())}
🎯 Чатов: {len(load_chats())}
🚀 Рассылка: {'✅ Активна' if mailing_active else '❌ Остановлена'}

━━━━━━━━━━━━━━━━━━━

🔐 **АВТОРИЗАЦИЯ:**
/auth - войти
/clean - удалить старую сессию
/status - статус сессии

📝 **ОБЪЯВЛЕНИЯ:**
/add [текст] - текст
/add_photo - фото + текст
/list - список
/del [ID] - удалить
/clear - очистить всё

🎯 **ЧАТЫ:**
/addchat [ссылка] - добавить
/removechat [номер] - удалить
/listchats - список
/clearchats - очистить всё

🚀 **ЗАПУСК:**
/startmail - запустить
/stopmail - остановить
/setdelay 150 400 - пауза

📊 **СТАТИСТИКА:**
/stats - показать
/check - проверить аккаунт"""
    
    bot.reply_to(msg, info, parse_mode="Markdown")

# ==================== FLASK ====================
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
    print(f"Telethon version: 1.43.2")
    print("=" * 50)
    
    threading.Thread(target=start_flask, daemon=True).start()
    
    print("Бот запущен!")
    print("Commands: /auth, /start, /startmail")
    
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
