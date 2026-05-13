import telebot
from telethon.sync import TelegramClient
from telethon import functions, types
from telethon.errors import FloodWaitError, SessionPasswordNeededError
import sqlite3
import threading
import time
import random
from datetime import datetime, timedelta
import json
import re
import os

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")
# ===================================================

# Состояния авторизации
auth_sessions = {}  # {chat_id: {"step": "phone", "phone": "", "client": None}}

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
mailing_thread = None

# Эмуляция базы данных через JSON
class SimpleDB:
    def __init__(self, filename="koreckt_data.json"):
        self.filename = filename
        self.data = self.load()
    
    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"ads": [], "history": [], "statistics": {"total": 0, "errors": 0}}
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_ad(self, text):
        ad_id = len(self.data["ads"]) + 1
        self.data["ads"].append({"id": ad_id, "text": text, "created": datetime.now().isoformat()})
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
    
    def get_stats(self):
        return self.data["statistics"]

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
    """Мощный движок рассылки"""
    global client
    
    print("🚀 KORECKT ENGINE V2.0 ЗАПУЩЕН")
    print("=" * 40)
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        if client is None or not client.is_connected():
            print("⚠️ Клиент не подключен, ждем авторизации...")
            time.sleep(10)
            continue
        
        ads = db.get_ads()
        if not ads:
            print("📭 База объявлений пуста. Ожидание...")
            time.sleep(30)
            continue
        
        ad = random.choice(ads)
        ad_text = ad["text"]
        
        if CONFIG["smart_delays"]:
            ad_text = format_message_with_emoji(ad_text)
        
        print(f"\n📢 НАЧАЛО НОВОГО КРУГА")
        print(f"📝 Объявление ID {ad['id']}: {ad_text[:50]}...")
        
        for idx, chat in enumerate(TARGET_CHATS):
            if not CONFIG["mailing_enabled"]:
                break
            
            print(f"\n🎯 Обработка чата: {chat}")
            smart_delay(3, 8, "Имитация входа в чат")
            
            try:
                print(f"✍️ Эмулируем набор текста...")
                typing_time = calculate_typing_time(ad_text)
                
                if CONFIG["smart_delays"] and len(ad_text) > 100:
                    parts = len(ad_text) // 50
                    for i in range(parts):
                        time.sleep(typing_time / parts)
                else:
                    time.sleep(typing_time)
                
                client.send_message(chat, ad_text)
                print(f"✅ УСПЕШНО ОТПРАВЛЕНО в {chat}")
                
                update_stats(True)
                db.add_history(ad["id"], chat, True)
                
                if CONFIG["stats"]["today_sent"] >= 100:
                    print("⚠️ Достигнут дневной лимит (100 сообщений). Пауза 30 мин.")
                    smart_delay(1800, 1800, "Дневной лимит")
                
            except FloodWaitError as e:
                print(f"⚠️ FLOOD WAIT: {e.seconds} секунд")
                time.sleep(e.seconds + 5)
                db.add_history(ad["id"], chat, False)
                
            except Exception as e:
                print(f"❌ ОШИБКА в {chat}: {e}")
                update_stats(False)
                db.add_history(ad["id"], chat, False)
                smart_delay(30, 60, "Пауза после ошибки")
            
            if idx < len(TARGET_CHATS) - 1:
                smart_delay(
                    CONFIG["delay_between_chats"]["min"],
                    CONFIG["delay_between_chats"]["max"],
                    "Пауза между чатами"
                )
        
        if CONFIG["mailing_enabled"] and ads:
            print(f"\n💤 КРУГ ЗАВЕРШЕН")
            
            if CONFIG["stats"]["errors"] > 10:
                wait_min, wait_max = 600, 900
                print("⚠️ Много ошибок, увеличиваю паузу")
            else:
                wait_min, wait_max = CONFIG["delay_between_rounds"]["min"], CONFIG["delay_between_rounds"]["max"]
            
            smart_delay(wait_min, wait_max, "Пауза между кругами")
            
            if CONFIG["stats"]["errors"] > 0:
                CONFIG["stats"]["errors"] = max(0, CONFIG["stats"]["errors"] - 1)

# ==================== АВТОРИЗАЦИЯ ЧЕРЕЗ БОТА ====================

def check_auth_status():
    """Проверка статуса авторизации"""
    global client
    try:
        if client and client.is_connected() and client.is_user_authorized():
            me = client.get_me()
            return True, me.first_name, me.username
        return False, None, None
    except:
        return False, None, None

@bot.message_handler(commands=['auth'])
def auth_cmd(msg):
    """Начать авторизацию"""
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    status, name, username = check_auth_status()
    if status:
        bot.reply_to(msg, f"✅ Вы уже авторизованы как **{name}** (@{username})\n\nДля переавторизации используйте /reauth", parse_mode="Markdown")
        return
    
    auth_sessions[msg.chat.id] = {"step": "phone", "phone": None, "client": None}
    bot.reply_to(msg, "🔐 **Авторизация в Telegram**\n\nОтправьте номер телефона в формате:\n`+71234567890`\n\nИли нажмите /cancel для отмены", parse_mode="Markdown")

@bot.message_handler(commands=['reauth'])
def reauth_cmd(msg):
    """Переавторизация"""
    if msg.from_user.id != ADMIN_ID:
        return
    
    global client
    try:
        if client:
            client.disconnect()
        client = None
    except:
        pass
    
    auth_sessions[msg.chat.id] = {"step": "phone", "phone": None, "client": None}
    bot.reply_to(msg, "🔄 **Переавторизация**\n\nОтправьте номер телефона в формате:\n`+71234567890`")

@bot.message_handler(commands=['cancel'])
def cancel_auth(msg):
    """Отмена авторизации"""
    if msg.from_user.id != ADMIN_ID:
        return
    
    if msg.chat.id in auth_sessions:
        del auth_sessions[msg.chat.id]
    bot.reply_to(msg, "❌ Авторизация отменена")

def process_phone_number(msg):
    """Обработка номера телефона"""
    phone = msg.text.strip()
    
    # Простая валидация
    if not re.match(r'^\+?\d{10,15}$', phone):
        bot.reply_to(msg, "❌ Неверный формат номера. Используйте:\n`+71234567890`\n\nПопробуйте снова или /cancel", parse_mode="Markdown")
        return False
    
    if not phone.startswith('+'):
        phone = '+' + phone
    
    try:
        # Создаем временный клиент
        temp_client = TelegramClient(f'temp_session_{msg.chat.id}', API_ID, API_HASH)
        temp_client.connect()
        
        if not temp_client.is_user_authorized():
            temp_client.send_code_request(phone)
            auth_sessions[msg.chat.id] = {
                "step": "code",
                "phone": phone,
                "client": temp_client
            }
            bot.reply_to(msg, "📱 **Код отправлен!**\n\nВведите код подтверждения из Telegram:\n(только цифры)")
            return True
        else:
            bot.reply_to(msg, "✅ Этот номер уже авторизован!")
            return False
            
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}\nПопробуйте снова или /cancel")
        return False

def process_code(msg):
    """Обработка кода подтверждения"""
    code = msg.text.strip()
    
    if not code.isdigit():
        bot.reply_to(msg, "❌ Код должен состоять только из цифр!\nПопробуйте снова или /cancel")
        return False
    
    session_data = auth_sessions.get(msg.chat.id)
    if not session_data or "client" not in session_data:
        bot.reply_to(msg, "❌ Сессия потеряна. Начните заново: /auth")
        return False
    
    temp_client = session_data["client"]
    phone = session_data["phone"]
    
    try:
        # Пытаемся войти с кодом
        temp_client.sign_in(phone, code)
        
        # Успешный вход
        global client
        if client:
            try:
                client.disconnect()
            except:
                pass
        
        # Сохраняем сессию
        session_file = "kor_session"
        temp_client.disconnect()
        
        # Создаем постоянный клиент
        client = TelegramClient(session_file, API_ID, API_HASH)
        client.connect()
        
        if not client.is_user_authorized():
            # Если не авторизован, используем временные данные
            client.sign_in(phone, code)
        
        me = client.get_me()
        
        # Очищаем временные данные
        del auth_sessions[msg.chat.id]
        
        bot.reply_to(msg, f"✅ **Авторизация успешна!**\n\n👤 Имя: {me.first_name}\n📱 Username: @{me.username if me.username else 'нет'}\n🆔 ID: {me.id}\n\n🚀 Теперь можно запускать рассылку: /startmail", parse_mode="Markdown")
        
        # Перезапускаем движок
        if mailing_thread and not mailing_thread.is_alive():
            restart_mailing_thread()
        
        return True
        
    except SessionPasswordNeededError:
        bot.reply_to(msg, "🔐 **Требуется двухфакторная аутентификация**\n\nВведите пароль от аккаунта:")
        auth_sessions[msg.chat.id]["step"] = "password"
        return False
        
    except Exception as e:
        error_msg = str(e)
        if "code" in error_msg.lower():
            bot.reply_to(msg, f"❌ Неверный код!\nПопробуйте снова или /cancel")
        else:
            bot.reply_to(msg, f"❌ Ошибка: {error_msg[:100]}\nПопробуйте /auth заново")
        return False

def process_password(msg):
    """Обработка 2FA пароля"""
    password = msg.text.strip()
    
    session_data = auth_sessions.get(msg.chat.id)
    if not session_data or "client" not in session_data:
        bot.reply_to(msg, "❌ Сессия потеряна. Начните заново: /auth")
        return False
    
    temp_client = session_data["client"]
    phone = session_data["phone"]
    
    try:
        temp_client.sign_in(password=password)
        
        global client
        if client:
            try:
                client.disconnect()
            except:
                pass
        
        session_file = "kor_session"
        temp_client.disconnect()
        
        client = TelegramClient(session_file, API_ID, API_HASH)
        client.connect()
        client.sign_in(phone, password=password)
        
        me = client.get_me()
        
        del auth_sessions[msg.chat.id]
        
        bot.reply_to(msg, f"✅ **Авторизация успешна!**\n\n👤 Имя: {me.first_name}\n📱 Username: @{me.username if me.username else 'нет'}\n🆔 ID: {me.id}\n\n🚀 Теперь можно запускать рассылку: /startmail", parse_mode="Markdown")
        
        if mailing_thread and not mailing_thread.is_alive():
            restart_mailing_thread()
        
        return True
        
    except Exception as e:
        bot.reply_to(msg, f"❌ Неверный пароль!\nПопробуйте снова или /cancel")
        return False

@bot.message_handler(func=lambda msg: msg.chat.id in auth_sessions)
def auth_handler(msg):
    """Обработчик шагов авторизации"""
    if msg.from_user.id != ADMIN_ID:
        return
    
    step = auth_sessions[msg.chat.id]["step"]
    
    if step == "phone":
        process_phone_number(msg)
    elif step == "code":
        process_code(msg)
    elif step == "password":
        process_password(msg)

# ==================== КОМАНДЫ БОТА ====================

def restart_mailing_thread():
    """Перезапуск потока рассылки"""
    global mailing_thread
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    status, name, username = check_auth_status()
    auth_status = "✅ Авторизован" if status else "❌ НЕ АВТОРИЗОВАН"
    auth_name = f" ({name})" if name else ""
    
    info = f"""
🔐 **KORECKT V2.0 - УЛЬТИМАТИВНЫЙ РАССЫЛЬЩИК**

📋 **Управление:**
/add [текст] - Добавить объявление
/list - Список объявлений
/del [ID] - Удалить объявление
/clear - Очистить всё
/stats - Статистика
/chats - Список чатов

🔐 **Авторизация:**
/auth - Войти в Telegram аккаунт
/reauth - Переавторизоваться

🚀 **Рассылка:**
/startmail - ЗАПУСК рассылки
/stopmail - ОСТАНОВ рассылки

⚙️ **Настройки:**
/config - Текущие настройки
/setdelay [мин] [макс] - Паузы между чатами
/setround [мин] [макс] - Паузы между кругами

📊 **Статус:**
🔐 Аккаунт: {auth_status}{auth_name}
🚀 Рассылка: {'🟢 АКТИВНА' if CONFIG['mailing_enabled'] else '🔴 ОСТАНОВЛЕНА'}
📝 Объявлений: {len(db.get_ads())}
✅ Отправлено сегодня: {CONFIG['stats']['today_sent']}
📈 Всего отправлено: {CONFIG['stats']['total_sent']}
❌ Ошибок: {CONFIG['stats']['errors']}
    """
    bot.send_message(msg.chat.id, info, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_ad_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ Укажите текст: /add Ваше объявление")
        return
    
    ad_id = db.add_ad(text)
    bot.reply_to(msg, f"✅ Объявление #{ad_id} добавлено!\nТекст: {text[:100]}...")

@bot.message_handler(commands=['list'])
def list_ads_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "📭 База пуста")
        return
    
    response = "📝 **Список объявлений:**\n\n"
    for ad in ads[-10:]:
        preview = ad['text'][:60] + "..." if len(ad['text']) > 60 else ad['text']
        response += f"*ID {ad['id']}:* {preview}\n\n"
    
    if len(ads) > 10:
        response += f"_...и еще {len(ads)-10} объявлений_"
    
    bot.send_message(msg.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_ad_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    try:
        ad_id = int(msg.text.replace('/del', '').strip())
        ad = db.get_ad_by_id(ad_id)
        if ad:
            db.delete_ad(ad_id)
            bot.reply_to(msg, f"✅ Объявление #{ad_id} удалено")
        else:
            bot.reply_to(msg, f"❌ Объявление #{ad_id} не найдено")
    except:
        bot.reply_to(msg, "❌ Укажите ID: /del 1")

@bot.message_handler(commands=['clear'])
def clear_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    db.clear_all()
    bot.reply_to(msg, "🗑️ База полностью очищена")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    ads = db.get_ads()
    history = db.data["history"]
    success_count = sum(1 for h in history if h["success"])
    
    response = f"""
📊 **ДЕТАЛЬНАЯ СТАТИСТИКА**

📝 Объявлений: {len(ads)}
✅ Успешных отправок: {success_count}
❌ Неудачных: {len(history) - success_count}
📈 Успешность: {(success_count/len(history)*100 if history else 0):.1f}%

🚀 Активность сегодня:
📨 Отправлено: {CONFIG['stats']['today_sent']}
⚠️ Ошибок: {CONFIG['stats']['errors']}

📊 Всего за всё время:
📬 Отправлено: {CONFIG['stats']['total_sent']}

🕒 Последние 5 отправок:
"""
    last_5 = history[-5:][::-1] if history else []
    for h in last_5:
        status = "✅" if h["success"] else "❌"
        time_str = h["time"][:19].replace("T", " ")
        response += f"\n{status} {time_str} → {h['chat']}"
    
    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['chats'])
def chats_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    response = "🎯 **Целевые чаты:**\n\n"
    for i, chat in enumerate(TARGET_CHATS, 1):
        response += f"{i}. {chat}\n"
    response += f"\n_Всего: {len(TARGET_CHATS)} чатов_"
    bot.send_message(msg.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['startmail'])
def start_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "❌ Невозможно запустить: база пуста!\nДобавьте объявления через /add")
        return
    
    status, name, _ = check_auth_status()
    if not status:
        bot.reply_to(msg, "❌ **Сначала авторизуйтесь!**\nИспользуйте команду /auth", parse_mode="Markdown")
        return
    
    if not CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = True
        bot.reply_to(msg, f"🚀 **РАССЫЛКА ЗАПУЩЕНА!**\n\n👤 Аккаунт: {name}\n📝 Объявлений: {len(db.get_ads())}\n🎯 Чатов: {len(TARGET_CHATS)}\n⚙️ Статус: АКТИВНА", parse_mode="Markdown")
        print("🚀 Рассылка запущена администратором")
    else:
        bot.reply_to(msg, "⚠️ Рассылка уже активна")

@bot.message_handler(commands=['stopmail'])
def stop_mail_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    if CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = False
        bot.reply_to(msg, "🛑 **РАССЫЛКА ОСТАНОВЛЕНА**")
        print("🛑 Рассылка остановлена администратором")
    else:
        bot.reply_to(msg, "⚠️ Рассылка уже остановлена")

@bot.message_handler(commands=['config'])
def config_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    response = f"""
⚙️ **ТЕКУЩАЯ КОНФИГУРАЦИЯ**

⏱️ Паузы между чатами: {CONFIG['delay_between_chats']['min']}-{CONFIG['delay_between_chats']['max']} сек
🔄 Паузы между кругами: {CONFIG['delay_between_rounds']['min']}-{CONFIG['delay_between_rounds']['max']} сек
⌨️ Скорость печати: {CONFIG['typing_speed']['min']}-{CONFIG['typing_speed']['max']} симв/сек
🛡️ Анти-флуд: {"ВКЛ" if CONFIG['anti_flood'] else "ВЫКЛ"}
🧠 Умные задержки: {"ВКЛ" if CONFIG['smart_delays'] else "ВЫКЛ"}

📊 Статус: {"АКТИВНА" if CONFIG['mailing_enabled'] else "ОСТАНОВЛЕНА"}
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
        bot.reply_to(msg, f"✅ Паузы между чатами: {min_d}-{max_d} сек")
    except:
        bot.reply_to(msg, "❌ Использование: /setdelay 150 400")

@bot.message_handler(commands=['setround'])
def set_round_cmd(msg):
    if msg.from_user.id != ADMIN_ID: return
    
    try:
        parts = msg.text.replace('/setround', '').strip().split()
        min_d = int(parts[0])
        max_d = int(parts[1])
        CONFIG["delay_between_rounds"]["min"] = min_d
        CONFIG["delay_between_rounds"]["max"] = max_d
        bot.reply_to(msg, f"✅ Паузы между кругами: {min_d}-{max_d} сек")
    except:
        bot.reply_to(msg, "❌ Использование: /setround 300 600")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT ULTIMATE V2.0")
    print("=" * 50)
    
    # Запуск движка в отдельном потоке
    restart_mailing_thread()
    
    print("🤖 Бот запущен и готов к работе!")
    print(f"👤 Ваш ID: {ADMIN_ID}")
    print("📱 Откройте Telegram и напишите /start")
    print("🔐 Для авторизации используйте /auth")
    print("=" * 50)
    
    # Запуск бота
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
