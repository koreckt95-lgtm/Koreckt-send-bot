import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
import threading
import time
import random
import json
import os
import asyncio
from datetime import datetime

# ==================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")

# ==================== ФАЙЛЫ ====================
CHATS_FILE = "chats.json"
ADS_FILE = "ads.json"

def load_chats():
    try:
        with open(CHATS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_chats(chats):
    with open(CHATS_FILE, 'w') as f:
        json.dump(chats, f)

def load_ads():
    try:
        with open(ADS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_ads(ads):
    with open(ADS_FILE, 'w') as f:
        json.dump(ads, f)

# ==================== НАСТРОЙКИ ====================
config = {
    "delay_min": 150,
    "delay_max": 400,
    "daily_limit": 100,
    "active": False
}

stats = {"sent": 0, "errors": 0, "today": 0, "last_date": datetime.now().date().isoformat()}

# ==================== ГЛОБАЛЬНЫЕ ====================
bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None
auth_sessions = {}
temp_media = {}

# ==================== АВТОРИЗАЦИЯ (ИСПРАВЛЕНА) ====================
@bot.message_handler(commands=['login'])
def login_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 Введите номер телефона:\nПример: +380123456789")

@bot.message_handler(commands=['logout'])
def logout_cmd(msg):
    global client
    if msg.from_user.id != ADMIN_ID:
        return
    if client:
        try:
            client.disconnect()
        except:
            pass
        client = None
    bot.reply_to(msg, "✅ Выход выполнен")

def process_auth(msg):
    chat_id = msg.chat.id
    step = auth_sessions[chat_id]["step"]
    
    if step == "phone":
        phone = msg.text.strip()
        if not phone.startswith("+"):
            phone = "+" + phone
        
        try:
            # СОЗДАЁМ НОВЫЙ КЛИЕНТ
            temp = TelegramClient(f'temp_{chat_id}', API_ID, API_HASH)
            temp.connect()
            temp.send_code_request(phone)
            auth_sessions[chat_id] = {"step": "code", "phone": phone, "client": temp}
            bot.reply_to(msg, "📱 Введите код из Telegram:")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")
            
    elif step == "code":
        code = msg.text.strip()
        data = auth_sessions[chat_id]
        
        try:
            data["client"].sign_in(data["phone"], code)
            global client
            # СОХРАНЯЕМ СЕССИЮ
            client = TelegramClient("kor_session", API_ID, API_HASH)
            client.connect()
            client.sign_in(data["phone"], code)
            me = client.get_me()
            del auth_sessions[chat_id]
            bot.reply_to(msg, f"✅ Авторизован: {me.first_name}\n\n/start - главное меню")
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
            client = TelegramClient("kor_session", API_ID, API_HASH)
            client.connect()
            client.sign_in(password=pwd)
            me = client.get_me()
            del auth_sessions[chat_id]
            bot.reply_to(msg, f"✅ Авторизован: {me.first_name}\n\n/start - главное меню")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")

# ==================== ОТПРАВКА ====================
def send_message(chat, text, photo=None):
    global client
    try:
        if not client or not client.is_connected():
            return False
        
        if photo:
            client.send_file(chat, photo, caption=text)
        else:
            # Имитация печати
            time.sleep(random.uniform(2, 6))
            client.send_message(chat, text)
        return True
    except FloodWaitError as e:
        print(f"Flood wait: {e.seconds}")
        time.sleep(e.seconds + 5)
        return False
    except Exception as e:
        print(f"Send error: {e}")
        return False

def mailing_loop():
    global stats, client
    
    while True:
        if not config["active"]:
            time.sleep(2)
            continue
        
        if not client or not client.is_connected():
            time.sleep(10)
            continue
        
        try:
            # Проверка авторизации
            if not client.is_user_authorized():
                time.sleep(10)
                continue
        except:
            time.sleep(10)
            continue
        
        ads = load_ads()
        chats = load_chats()
        
        if not ads or not chats:
            time.sleep(30)
            continue
        
        # Дневной лимит
        today = datetime.now().date().isoformat()
        if stats["last_date"] != today:
            stats["today"] = 0
            stats["last_date"] = today
        
        if stats["today"] >= config["daily_limit"]:
            config["active"] = False
            print("Дневной лимит достигнут")
            continue
        
        # Выбираем случайное объявление
        ad = random.choice(ads)
        
        print(f"Рассылка: {ad.get('text', '')[:50]}...")
        
        for chat in chats:
            if not config["active"]:
                break
            
            success = send_message(chat, ad.get("text", ""), ad.get("photo"))
            
            if success:
                stats["sent"] += 1
                stats["today"] += 1
                print(f"✅ {chat}")
            else:
                stats["errors"] += 1
                print(f"❌ {chat}")
                time.sleep(60)
            
            # Пауза между чатами
            delay = random.uniform(config["delay_min"], config["delay_max"])
            print(f"Пауза {delay:.0f} сек...")
            time.sleep(delay)
        
        # Пауза между кругами
        print("Круг завершён, пауза 5-10 минут...")
        time.sleep(random.uniform(300, 600))

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещён")
        return
    
    is_auth = client and client.is_connected() if client else False
    try:
        if is_auth:
            me = client.get_me()
            auth_text = f"✅ {me.first_name}"
        else:
            auth_text = "❌ Не авторизован"
    except:
        auth_text = "❌ Не авторизован"
    
    ads_count = len(load_ads())
    chats_count = len(load_chats())
    
    text = f"""
🤖 **KORECKT БОТ**

🔐 Авторизация: {auth_text}
📝 Объявлений: {ads_count}
🎯 Чатов: {chats_count}
📊 Отправлено сегодня: {stats['today']}/{config['daily_limit']}
🚀 Рассылка: {'🟢 Активна' if config['active'] else '🔴 Остановлена'}

━━━━━━━━━━━━━━━━━

📝 **ОБЪЯВЛЕНИЯ:**
/add_text Текст - Текст
/add_photo - Фото + текст
/list - Список
/del [ID] - Удалить

🎯 **ЧАТЫ:**
/addchat [ссылка] - Добавить
/removechat [ID] - Удалить
/listchats - Список

🚀 **УПРАВЛЕНИЕ:**
/startmail - Запуск
/stopmail - Остановка
/setdelay [мин] [макс] - Пауза
/setdaily [лимит] - Лимит

🔐 **АВТОРИЗАЦИЯ:**
/login - Войти
/logout - Выйти
/check - Проверить

📊 **СТАТИСТИКА:**
/stats - Показать
"""
    bot.reply_to(msg, text, parse_mode="Markdown")

@bot.message_handler(commands=['add_text'])
def add_text(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add_text', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add_text Текст объявления")
        return
    
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "text", "text": text, "photo": None})
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
    data = temp_media[msg.chat.id]
    if "photo" in data:
        ads = load_ads()
        ad_id = len(ads) + 1
        ads.append({"id": ad_id, "type": "photo", "text": "", "photo": data["photo"]})
        save_ads(ads)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото без текста)")
    del temp_media[msg.chat.id]

@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    if msg.chat.id not in temp_media:
        return
    photo = msg.photo[-1].file_id
    temp_media[msg.chat.id] = {"step": "text", "photo": photo}
    bot.reply_to(msg, "📝 Отправьте ТЕКСТ для фото (или /skip)")

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
    
    text = "📝 **Объявления:**\n\n"
    for ad in ads[-10:]:
        preview = ad.get('text', 'Без текста')[:40]
        text += f"`ID {ad['id']}` [{ad['type']}]: {preview}\n"
    bot.reply_to(msg, text, parse_mode="Markdown")

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
    
    text = "🎯 **Чаты:**\n\n"
    for i, chat in enumerate(chats[:30], 1):
        short = chat.replace("https://t.me/", "@")
        text += f"{i}. {short}\n"
    if len(chats) > 30:
        text += f"\n...и ещё {len(chats)-30}"
    bot.reply_to(msg, text, parse_mode="Markdown")

@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not client or not client.is_connected():
        bot.reply_to(msg, "❌ Сначала авторизуйтесь: /login")
        return
    
    if len(load_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений: /add_text")
        return
    
    if len(load_chats()) == 0:
        bot.reply_to(msg, "❌ Нет чатов: /addchat")
        return
    
    config["active"] = True
    bot.reply_to(msg, "🚀 **Рассылка запущена!**\n/stopmail - остановить")

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    config["active"] = False
    bot.reply_to(msg, "🛑 **Рассылка остановлена**")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        config["delay_min"] = int(parts[0])
        config["delay_max"] = int(parts[1])
        bot.reply_to(msg, f"✅ Пауза: {config['delay_min']}-{config['delay_max']} сек")
    except:
        bot.reply_to(msg, "❌ /setdelay 150 400")

@bot.message_handler(commands=['setdaily'])
def set_daily(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        limit = int(msg.text.replace('/setdaily', '').strip())
        config["daily_limit"] = limit
        bot.reply_to(msg, f"✅ Дневной лимит: {limit}")
    except:
        bot.reply_to(msg, "❌ /setdaily 100")

@bot.message_handler(commands=['stats'])
def show_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    success_rate = 0
    total = stats["sent"] + stats["errors"]
    if total > 0:
        success_rate = stats["sent"] / total * 100
    
    text = f"""
📊 **СТАТИСТИКА**

📨 Всего отправлено: {stats['sent']}
❌ Ошибок: {stats['errors']}
📈 Успешность: {success_rate:.1f}%

📅 Сегодня: {stats['today']}/{config['daily_limit']}
🎯 Чатов: {len(load_chats())}
📝 Объявлений: {len(load_ads())}

🚀 Рассылка: {'🟢 Активна' if config['active'] else '🔴 Остановлена'}
"""
    bot.reply_to(msg, text, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def check_account(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not client or not client.is_connected():
        bot.reply_to(msg, "❌ Не авторизован. /login")
        return
    
    try:
        me = client.get_me()
        text = f"""
✅ **Аккаунт в порядке**

👤 Имя: {me.first_name}
🆔 ID: {me.id}
📱 Premium: {'Да' if me.premium else 'Нет'}

⚠️ Бан: Не обнаружен
"""
        bot.reply_to(msg, text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.chat.id in auth_sessions)
def auth_handler(msg):
    process_auth(msg)

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("🤖 Бот запущен")
    
    # Запуск рассылки в фоне
    thread = threading.Thread(target=mailing_loop, daemon=True)
    thread.start()
    
    # Flask для Render
    try:
        from flask import Flask
        flask_app = Flask(__name__)
        
        @flask_app.route('/')
        def home():
            return "KORECKT Bot is running!"
        
        @flask_app.route('/health')
        def health():
            return "OK"
        
        port = int(os.environ.get("PORT", 8080))
        threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=port, debug=False), daemon=True).start()
        print(f"🌐 Flask сервер на порту {port}")
    except Exception as e:
        print(f"⚠️ Flask не запущен: {e}")
    
    # Запуск бота
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
