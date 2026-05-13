import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
import threading
import time
import random
from datetime import datetime
import json
import os
import re
from flask import Flask

# ==================== КОНФИГ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Koreckt Bot is running!", 200

# Простое хранилище данных
DATA_FILE = "data.json"
data_lock = threading.Lock()

def get_data():
    with data_lock:
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"ads": [], "stats": {"sent": 0, "errors": 0}}

def save_data(data):
    with data_lock:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)

# Конфиг рассылки
mailing = {
    "active": False,
    "today_sent": 0,
    "last_date": datetime.now().date().isoformat()
}

bot = telebot.TeleBot(BOT_TOKEN)
user_client = None
auth_states = {}

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
def update_stats(success=True):
    today = datetime.now().date().isoformat()
    if mailing["last_date"] != today:
        mailing["today_sent"] = 0
        mailing["last_date"] = today
    
    if success:
        mailing["today_sent"] += 1
        data = get_data()
        data["stats"]["sent"] += 1
        save_data(data)

def add_ad(text):
    data = get_data()
    ad_id = len(data["ads"]) + 1
    data["ads"].append({"id": ad_id, "text": text})
    save_data(data)
    return ad_id

def get_ads():
    return get_data()["ads"]

def delete_ad(ad_id):
    data = get_data()
    data["ads"] = [a for a in data["ads"] if a["id"] != ad_id]
    save_data(data)

def clear_ads():
    data = get_data()
    data["ads"] = []
    save_data(data)

def smart_sleep(seconds, msg=""):
    if msg:
        print(msg)
    for i in range(int(seconds)):
        if not mailing["active"]:
            break
        time.sleep(1)

# ==================== ДВИЖОК РАССЫЛКИ ====================
def mailing_engine():
    global user_client
    print("🔄 Движок рассылки запущен и ждет авторизации...")
    
    while user_client is None:
        time.sleep(3)
    
    print(f"✅ Авторизован как: {user_client.get_me().first_name}")
    
    while True:
        if not mailing["active"]:
            time.sleep(2)
            continue
        
        if user_client is None:
            print("⚠️ Клиент потерян")
            time.sleep(10)
            continue
        
        ads = get_ads()
        if not ads:
            print("📭 Нет объявлений")
            time.sleep(30)
            continue
        
        # Берем случайное объявление
        ad = ads[random.randint(0, len(ads)-1)]
        print(f"\n📢 Начинаем рассылку: {ad['text'][:50]}...")
        
        for chat in TARGET_CHATS:
            if not mailing["active"]:
                break
            
            print(f"📨 Отправка в {chat}")
            
            try:
                # Имитация набора
                time.sleep(random.uniform(3, 8))
                user_client.send_message(chat, ad["text"])
                print(f"✅ Успешно в {chat}")
                update_stats(True)
                
                # Пауза между чатами
                pause = random.uniform(150, 400)
                print(f"⏳ Пауза {pause:.0f} сек")
                smart_sleep(pause)
                
            except FloodWaitError as e:
                print(f"⚠️ Flood: ждем {e.seconds} сек")
                time.sleep(e.seconds)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                update_stats(False)
                time.sleep(60)
        
        # Пауза между кругами
        if mailing["active"]:
            pause = random.uniform(300, 600)
            print(f"\n💤 Круг завершен. Пауза {pause:.0f} сек\n")
            smart_sleep(pause)

# ==================== КОМАНДЫ БОТА ====================
@bot.message_handler(commands=['start'])
def start_command(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    ads = get_ads()
    status = "🟢 РАБОТАЕТ" if mailing["active"] else "🔴 ОСТАНОВЛЕН"
    auth_status = "✅ Есть" if user_client else "❌ Нет"
    
    text = f"""
🤖 KORECKT BOT V2.0

📊 СТАТУС:
├─ Аккаунт: {auth_status}
├─ Рассылка: {status}
├─ Объявлений: {len(ads)}
├─ Отправлено сегодня: {mailing['today_sent']}
└─ Всего ошибок: {get_data()['stats']['errors']}

📋 КОМАНДЫ:
/login - Войти в аккаунт
/logout - Выйти из аккаунта
/add [текст] - Добавить объявление
/list - Список объявлений
/del [ID] - Удалить объявление
/clear - Очистить все
/startmail - Запустить рассылку
/stopmail - Остановить рассылку
/stats - Статистика
/chats - Список чатов
    """
    bot.reply_to(msg, text)

@bot.message_handler(commands=['login'])
def login_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if user_client:
        bot.reply_to(msg, "✅ Уже авторизован. /logout для выхода")
        return
    
    auth_states[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 Введите номер телефона в формате:\n+71234567890")

@bot.message_handler(commands=['logout'])
def logout_command(msg):
    global user_client
    if user_client:
        try:
            user_client.disconnect()
        except:
            pass
        user_client = None
    bot.reply_to(msg, "✅ Вы вышли из аккаунта")

@bot.message_handler(commands=['add'])
def add_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ Использование: /add текст объявления")
        return
    ad_id = add_ad(text)
    bot.reply_to(msg, f"✅ Объявление #{ad_id} добавлено")

@bot.message_handler(commands=['list'])
def list_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    ads = get_ads()
    if not ads:
        bot.reply_to(msg, "📭 Нет объявлений")
        return
    response = "📝 СПИСОК ОБЪЯВЛЕНИЙ:\n\n"
    for ad in ads:
        preview = ad['text'][:50] + "..." if len(ad['text']) > 50 else ad['text']
        response += f"#{ad['id']}: {preview}\n"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['del'])
def delete_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        delete_ad(ad_id)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
    except:
        bot.reply_to(msg, "❌ Использование: /del 1")

@bot.message_handler(commands=['clear'])
def clear_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    clear_ads()
    bot.reply_to(msg, "✅ Все объявления удалены")

@bot.message_handler(commands=['startmail'])
def start_mail_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not user_client:
        bot.reply_to(msg, "❌ Сначала войдите в аккаунт: /login")
        return
    if len(get_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений. Добавьте: /add")
        return
    mailing["active"] = True
    bot.reply_to(msg, f"🚀 РАССЫЛКА ЗАПУЩЕНА!\nЧатов: {len(TARGET_CHATS)}\nОбъявлений: {len(get_ads())}")

@bot.message_handler(commands=['stopmail'])
def stop_mail_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    mailing["active"] = False
    bot.reply_to(msg, "🛑 РАССЫЛКА ОСТАНОВЛЕНА")

@bot.message_handler(commands=['stats'])
def stats_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    data = get_data()
    text = f"""
📊 СТАТИСТИКА:
├─ Отправлено всего: {data['stats']['sent']}
├─ Отправлено сегодня: {mailing['today_sent']}
├─ Ошибок: {data['stats']['errors']}
├─ Объявлений: {len(data['ads'])}
└─ Чатов: {len(TARGET_CHATS)}
    """
    bot.reply_to(msg, text)

@bot.message_handler(commands=['chats'])
def chats_command(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = "🎯 ЦЕЛЕВЫЕ ЧАТЫ:\n\n"
    for i, chat in enumerate(TARGET_CHATS, 1):
        text += f"{i}. {chat}\n"
    bot.reply_to(msg, text)

# Обработка авторизации
@bot.message_handler(func=lambda m: m.chat.id in auth_states)
def auth_handler(msg):
    global user_client
    chat_id = msg.chat.id
    text = msg.text.strip()
    state = auth_states[chat_id]
    
    if state["step"] == "phone":
        if not re.match(r'^\+\d{10,15}$', text):
            bot.reply_to(msg, "❌ Неверный формат. Пример: +71234567890")
            return
        
        state["phone"] = text
        state["step"] = "code"
        
        try:
            client = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
            state["client"] = client
            client.connect()
            client.send_code_request(text)
            bot.reply_to(msg, "📱 Код отправлен! Введите код из Telegram:")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}")
            del auth_states[chat_id]
    
    elif state["step"] == "code":
        try:
            client = state["client"]
            client.sign_in(state["phone"], text)
            user_client = client
            bot.reply_to(msg, f"✅ УСПЕШНЫЙ ВХОД!\nАккаунт: {client.get_me().first_name}\n\nТеперь можно запустить рассылку: /startmail")
            del auth_states[chat_id]
        except Exception as e:
            if "2FA" in str(e) or "password" in str(e).lower():
                state["step"] = "password"
                bot.reply_to(msg, "🔐 Введите пароль двухфакторной аутентификации:")
            else:
                bot.reply_to(msg, f"❌ Ошибка: {str(e)[:150]}")
                del auth_states[chat_id]
    
    elif state["step"] == "password":
        try:
            client = state["client"]
            client.sign_in(password=text)
            user_client = client
            bot.reply_to(msg, f"✅ УСПЕШНЫЙ ВХОД!\nАккаунт: {client.get_me().first_name}\n\nТеперь можно запустить рассылку: /startmail")
            del auth_states[chat_id]
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:150]}")
            del auth_states[chat_id]

# ==================== ЗАПУСК ====================
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT BOT ДЛЯ RENDER")
    print("=" * 50)
    
    # Запускаем Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Запускаем движок рассылки
    threading.Thread(target=mailing_engine, daemon=True).start()
    
    # Запускаем бота
    print("🤖 Бот запущен!")
    print(f"👤 ADMIN ID: {ADMIN_ID}")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
