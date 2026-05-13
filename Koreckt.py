import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
from telethon import functions, types
import threading
import time
import random
from datetime import datetime
import os
import re
import json
from flask import Flask

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = [c.strip() for c in os.environ.get("TARGET_CHATS", "").split(",") if c.strip()]

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Koreckt Bot Running", 200

# ==================== ХРАНЕНИЕ В ПАМЯТИ (НЕТ ФАЙЛОВОЙ БД!) ====================
ads = []
stats = {"sent": 0, "today": 0, "errors": 0, "last_date": datetime.now().date().isoformat()}
mailing_active = False
user_client = None
auth_sessions = {}  # {chat_id: {"step": "phone", "phone": "", "client": None}}

bot = telebot.TeleBot(BOT_TOKEN)

# ==================== ФУНКЦИИ ====================
def add_ad(text):
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "text": text, "sent_count": 0})
    return ad_id

def get_ads():
    return ads.copy()

def delete_ad(ad_id):
    global ads
    ads = [a for a in ads if a["id"] != ad_id]

def clear_ads():
    global ads
    ads = []

def update_stats(success=True):
    global stats
    today = datetime.now().date().isoformat()
    if stats["last_date"] != today:
        stats["today"] = 0
        stats["last_date"] = today
    if success:
        stats["sent"] += 1
        stats["today"] += 1
    else:
        stats["errors"] += 1

def human_delay(min_sec, max_sec, reason=""):
    delay = random.uniform(min_sec, max_sec)
    if reason:
        print(f"🧠 {reason}: {delay:.1f} сек")
    time.sleep(delay)

# ==================== ДВИЖОК РАССЫЛКИ ====================
def mailing_engine():
    global user_client, mailing_active
    
    print("🚀 ДВИЖОК ЗАПУЩЕН, ЖДУ АВТОРИЗАЦИЮ...")
    
    while user_client is None:
        time.sleep(3)
    
    print(f"✅ АВТОРИЗОВАН: {user_client.get_me().first_name}")
    print(f"🎯 ЧАТОВ: {len(TARGET_CHATS)}")
    
    while True:
        if not mailing_active:
            time.sleep(2)
            continue
        
        if user_client is None:
            time.sleep(10)
            continue
        
        current_ads = get_ads()
        if not current_ads:
            print("📭 НЕТ ОБЪЯВЛЕНИЙ")
            time.sleep(30)
            continue
        
        # Выбираем случайное объявление
        ad = random.choice(current_ads)
        print(f"\n📢 НОВЫЙ КРУГ. Объявление #{ad['id']}: {ad['text'][:50]}...")
        
        # Перемешиваем чаты
        chats = TARGET_CHATS.copy()
        random.shuffle(chats)
        
        for idx, chat in enumerate(chats):
            if not mailing_active:
                break
            
            print(f"📨 Отправка в {chat}...")
            
            try:
                # Имитация набора текста
                user_client(functions.messages.SetTypingRequest(
                    peer=chat,
                    action=types.SendMessageTypingAction()
                ))
                
                # Время на набор
                typing_time = len(ad["text"]) / random.uniform(5, 12)
                time.sleep(typing_time)
                
                # Отправка
                user_client.send_message(chat, ad["text"])
                print(f"✅ УСПЕШНО")
                update_stats(True)
                ad["sent_count"] += 1
                
                # Пауза после отправки
                human_delay(60, 180, "Пауза после отправки")
                
            except FloodWaitError as e:
                print(f"⚠️ FLOOD: {e.seconds} сек")
                time.sleep(e.seconds + 10)
                update_stats(False)
            except Exception as e:
                print(f"❌ ОШИБКА: {e}")
                update_stats(False)
                human_delay(60, 120, "Пауза после ошибки")
            
            # Пауза между чатами
            if idx < len(chats) - 1:
                human_delay(180, 600, "Пауза между чатами")
        
        # Пауза между кругами
        if mailing_active:
            human_delay(600, 1800, "Отдых между кругами")

# ==================== КОМАНДЫ БОТА ====================
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ ДОСТУП ЗАПРЕЩЕН")
        return
    
    auth_status = "✅ ЕСТЬ" if user_client else "❌ НЕТ"
    mail_status = "🟢 РАБОТАЕТ" if mailing_active else "🔴 СТОП"
    
    text = f"""
🤖 **KORECKT BOT V2.0**

📊 **СТАТУС:**
├─ Аккаунт: {auth_status}
├─ Рассылка: {mail_status}
├─ Объявлений: {len(get_ads())}
├─ Отправлено сегодня: {stats['today']}
├─ Всего отправлено: {stats['sent']}
└─ Ошибок: {stats['errors']}

📋 **КОМАНДЫ:**
/login - Войти в аккаунт
/logout - Выйти из аккаунта
/add [текст] - Добавить объявление
/list - Список объявлений
/del [ID] - Удалить объявление
/clear - Очистить всё
/startmail - ЗАПУСТИТЬ рассылку
/stopmail - ОСТАНОВИТЬ рассылку
/stats - Статистика
/chats - Список чатов

⚡ **НАСТРОЙКИ:**
/setlimit [число] - Дневной лимит (по умолч. 50)
    """
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['login'])
def login_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if user_client:
        bot.reply_to(msg, "✅ Уже авторизован. /logout для выхода")
        return
    
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 **ВХОД В АККАУНТ**\n\nВведите номер телефона в формате:\n`+71234567890`", parse_mode="Markdown")

@bot.message_handler(commands=['logout'])
def logout_cmd(msg):
    global user_client
    if msg.from_user.id != ADMIN_ID:
        return
    
    if user_client:
        try:
            user_client.disconnect()
        except:
            pass
        user_client = None
    
    bot.reply_to(msg, "✅ Вы вышли из аккаунта")

@bot.message_handler(commands=['add'])
def add_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ Использование: `/add Текст объявления`", parse_mode="Markdown")
        return
    
    ad_id = add_ad(text)
    bot.reply_to(msg, f"✅ **Объявление #{ad_id} добавлено!**\n\nТекст: {text[:100]}")

@bot.message_handler(commands=['list'])
def list_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    current_ads = get_ads()
    if not current_ads:
        bot.reply_to(msg, "📭 Нет объявлений")
        return
    
    response = "📝 **СПИСОК ОБЪЯВЛЕНИЙ:**\n\n"
    for ad in current_ads:
        preview = ad['text'][:50] + "..." if len(ad['text']) > 50 else ad['text']
        response += f"`#{ad['id']}` - {preview}\n📤 Отправлено: {ad['sent_count']} раз\n\n"
    
    bot.send_message(msg.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        delete_ad(ad_id)
        bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
    except:
        bot.reply_to(msg, "❌ Использование: `/del 1`", parse_mode="Markdown")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    clear_ads()
    bot.reply_to(msg, "✅ Все объявления удалены")

@bot.message_handler(commands=['startmail'])
def start_mail_cmd(msg):
    global mailing_active
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not user_client:
        bot.reply_to(msg, "❌ **Сначала войдите в аккаунт!**\nИспользуйте `/login`", parse_mode="Markdown")
        return
    
    if not get_ads():
        bot.reply_to(msg, "❌ **Нет объявлений!**\nДобавьте через `/add`", parse_mode="Markdown")
        return
    
    mailing_active = True
    bot.reply_to(msg, f"🚀 **РАССЫЛКА ЗАПУЩЕНА!**\n\n📝 Объявлений: {len(get_ads())}\n🎯 Чатов: {len(TARGET_CHATS)}\n⚡ Режим: имитация человека")

@bot.message_handler(commands=['stopmail'])
def stop_mail_cmd(msg):
    global mailing_active
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    mailing_active = False
    bot.reply_to(msg, "🛑 **РАССЫЛКА ОСТАНОВЛЕНА**")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    current_ads = get_ads()
    
    text = f"""
📊 **СТАТИСТИКА**

📨 Отправлено сегодня: {stats['today']}
📬 Всего отправлено: {stats['sent']}
❌ Ошибок: {stats['errors']}
📝 Объявлений: {len(current_ads)}
🎯 Чатов: {len(TARGET_CHATS)}

📈 **УСПЕШНОСТЬ:** {((stats['sent'] - stats['errors']) / max(stats['sent'], 1) * 100):.1f}%
    """
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['chats'])
def chats_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    text = "🎯 **ЦЕЛЕВЫЕ ЧАТЫ:**\n\n"
    for i, chat in enumerate(TARGET_CHATS, 1):
        text += f"{i}. {chat}\n"
    text += f"\n📊 Всего: {len(TARGET_CHATS)}"
    
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['setlimit'])
def set_limit_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        limit = int(msg.text.replace('/setlimit', '').strip())
        if 1 <= limit <= 500:
            # Сохраняем в глобальную переменную
            global daily_limit
            daily_limit = limit
            bot.reply_to(msg, f"✅ Дневной лимит установлен: {limit} сообщений")
        else:
            bot.reply_to(msg, "❌ Лимит должен быть от 1 до 500")
    except:
        bot.reply_to(msg, "❌ Использование: `/setlimit 50`", parse_mode="Markdown")

# ==================== АВТОРИЗАЦИЯ ЧЕРЕЗ БОТА ====================
@bot.message_handler(func=lambda m: m.chat.id in auth_sessions)
def auth_handler(msg):
    global user_client
    
    chat_id = msg.chat.id
    text = msg.text.strip()
    session = auth_sessions[chat_id]
    
    if session["step"] == "phone":
        # Проверка формата
        if not re.match(r'^\+\d{10,15}$', text):
            bot.reply_to(msg, "❌ Неверный формат. Пример: +71234567890\nПопробуйте снова")
            return
        
        session["phone"] = text
        session["step"] = "code"
        
        try:
            # Создаем клиент с уникальным именем сессии
            temp_client = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
            session["client"] = temp_client
            temp_client.connect()
            temp_client.send_code_request(text)
            bot.reply_to(msg, "📱 **КОД ОТПРАВЛЕН!**\n\nВведите код из Telegram (только цифры):")
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}\nНачните заново: /login")
            del auth_sessions[chat_id]
    
    elif session["step"] == "code":
        if not text.isdigit():
            bot.reply_to(msg, "❌ Код должен содержать только цифры")
            return
        
        try:
            client = session["client"]
            client.sign_in(session["phone"], text)
            user_client = client
            
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            
            bot.reply_to(msg, f"✅ **УСПЕШНЫЙ ВХОД!**\n\n👤 Аккаунт: {username}\n🆔 ID: {me.id}\n\nТеперь можно запустить рассылку: `/startmail`", parse_mode="Markdown")
            del auth_sessions[chat_id]
            
        except Exception as e:
            error = str(e)
            if "2FA" in error or "password" in error.lower():
                session["step"] = "password"
                bot.reply_to(msg, "🔐 **ТРЕБУЕТСЯ ПАРОЛЬ 2FA**\n\nВведите пароль от аккаунта:")
            else:
                bot.reply_to(msg, f"❌ Ошибка: {error[:150]}\nНачните заново: /login")
                del auth_sessions[chat_id]
    
    elif session["step"] == "password":
        try:
            client = session["client"]
            client.sign_in(password=text)
            user_client = client
            
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            
            bot.reply_to(msg, f"✅ **УСПЕШНЫЙ ВХОД!**\n\n👤 Аккаунт: {username}\n🆔 ID: {me.id}\n\nТеперь можно запустить рассылку: `/startmail`", parse_mode="Markdown")
            del auth_sessions[chat_id]
            
        except Exception as e:
            bot.reply_to(msg, f"❌ Ошибка: {str(e)[:150]}\nНачните заново: /login")
            del auth_sessions[chat_id]

# ==================== ЗАПУСК ====================
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT BOT V2.0 ДЛЯ RENDER")
    print("=" * 50)
    
    # Запуск Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Запуск движка рассылки
    threading.Thread(target=mailing_engine, daemon=True).start()
    
    print("🤖 БОТ ЗАПУЩЕН!")
    print(f"👤 ADMIN ID: {ADMIN_ID}")
    print(f"🎯 ЧАТОВ: {len(TARGET_CHATS)}")
    print("=" * 50)
    print("📱 ОТКРОЙТЕ TELEGRAM И НАПИШИТЕ /start")
    print("🔑 ДЛЯ ВХОДА ИСПОЛЬЗУЙТЕ /login")
    print("=" * 50)
    
    # Запуск бота
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
