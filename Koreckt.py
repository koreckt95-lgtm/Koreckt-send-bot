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

# ==================== НАСТРОЙКИ (ВСТАВЬТЕ СВОИ ДАННЫЕ) ====================
# ===== ДАННЫЕ БЕРУТСЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (БЕЗОПАСНО!) =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
TARGET_CHATS = os.environ.get("TARGET_CHATS", "").split(",")
# =========================================================================

# Конфигурация для Pydroid3 (хранение в памяти)
CONFIG = {
    "mailing_enabled": False,
    "stats": {
        "total_sent": 0,
        "today_sent": 0,
        "errors": 0,
        "last_date": datetime.now().date().isoformat()
    },
    "delay_between_chats": {"min": 150, "max": 400"},
    "delay_between_rounds": {"min": 300, "max": 600},
    "typing_speed": {"min": 5, "max": 12},
    "anti_flood": True,
    "smart_delays": True
}

bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None

# Данные для авторизации
auth_data = {
    "phone": None,
    "code": None,
    "password": None,
    "step": None,
    "client": None
}

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
    global client
    
    print("🚀 KORECKT ENGINE V2.0 ЗАПУЩЕН")
    print("=" * 40)
    
    if client is None:
        print("⚠️ Клиент не авторизован. Ожидание входа...")
        while client is None and CONFIG["mailing_enabled"]:
            time.sleep(5)
        if client is None:
            print("❌ Авторизация не выполнена. Движок остановлен.")
            return
    
    try:
        me = client.get_me()
        print(f"✅ Юзербот успешно авторизован")
        print(f"👤 Аккаунт: {me.first_name}")
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        return
    
    print("=" * 40)
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        if client is None:
            print("⚠️ Клиент потерян. Ожидание переподключения...")
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
            
            if client is None:
                break
            
            print(f"\n🎯 Обработка чата: {chat}")
            
            smart_delay(3, 8, "Имитация входа в чат")
            
            try:
                print(f"✍️ Эмулируем набор текста...")
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
        
        if CONFIG["mailing_enabled"] and ads and client is not None:
            print(f"\n💤 КРУГ ЗАВЕРШЕН")
            
            if CONFIG["stats"]["errors"] > 10:
                wait_min, wait_max = 600, 900
                print("⚠️ Много ошибок, увеличиваю паузу")
            else:
                wait_min, wait_max = CONFIG["delay_between_rounds"]["min"], CONFIG["delay_between_rounds"]["max"]
            
            smart_delay(wait_min, wait_max, "Пауза между кругами")
            
            if CONFIG["stats"]["errors"] > 0:
                CONFIG["stats"]["errors"] = max(0, CONFIG["stats"]["errors"] - 1)

# ==================== ФУНКЦИИ АВТОРИЗАЦИИ ====================

@bot.message_handler(commands=['login'])
def login_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    if client is not None:
        try:
            me = client.get_me()
            bot.reply_to(msg, f"✅ Вы уже авторизованы как @{me.username or me.first_name}\nИспользуйте /logout для выхода")
            return
        except:
            global client
            client = None
    
    auth_data["step"] = "phone"
    auth_data["phone"] = None
    auth_data["code"] = None
    auth_data["password"] = None
    
    bot.reply_to(msg, "🔐 **Вход в аккаунт Telegram**\n\nВведите номер телефона в международном формате:\n`+71234567890`", parse_mode="Markdown")

@bot.message_handler(commands=['logout'])
def logout_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    global client
    if client:
        try:
            client.disconnect()
        except:
            pass
        client = None
    
    auth_data["step"] = None
    bot.reply_to(msg, "✅ Вы вышли из аккаунта Telegram")

@bot.message_handler(commands=['cancel'])
def cancel_auth_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    if auth_data["client"]:
        try:
            auth_data["client"].disconnect()
        except:
            pass
    
    auth_data["step"] = None
    auth_data["client"] = None
    bot.reply_to(msg, "❌ Авторизация отменена")

def process_auth_step(message):
    global client
    
    user_id = message.from_user.id
    text = message.text.strip()
    
    if auth_data["step"] == "phone":
        if not re.match(r'^\+?\d{10,15}$', text):
            bot.reply_to(message, "❌ Неверный формат номера. Пример: +71234567890\nПопробуйте снова или /cancel для отмены")
            return
        
        auth_data["phone"] = text
        
        try:
            temp_client = TelegramClient('temp_auth_session', API_ID, API_HASH)
            auth_data["client"] = temp_client
            
            bot.reply_to(message, "⏳ Отправка кода подтверждения...")
            temp_client.connect()
            temp_client.send_code_request(auth_data["phone"])
            
            auth_data["step"] = "code"
            bot.reply_to(message, "📱 **Код подтверждения отправлен**\n\nВведите код из Telegram (только цифры):\n_Пример: 12345_", parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка при отправке кода: {str(e)[:100]}\nПопробуйте /login заново")
            auth_data["step"] = None
            auth_data["client"] = None
    
    elif auth_data["step"] == "code":
        if not text.isdigit():
            bot.reply_to(message, "❌ Код должен состоять только из цифр\nПопробуйте снова или /cancel для отмены")
            return
        
        auth_data["code"] = text
        
        try:
            bot.reply_to(message, "⏳ Проверка кода...")
            
            auth_data["client"].sign_in(auth_data["phone"], auth_data["code"])
            
            client = auth_data["client"]
            restart_engine_with_client()
            
            me = client.get_me()
            bot.reply_to(message, f"✅ **Успешный вход!**\n\n👤 Аккаунт: @{me.username or me.first_name}\n🆔 ID: {me.id}\n\nТеперь можно запускать рассылку через /startmail", parse_mode="Markdown")
            
            auth_data["step"] = None
            auth_data["client"] = None
            
        except Exception as e:
            error_msg = str(e)
            
            if "2FA" in error_msg or "password" in error_msg.lower():
                auth_data["step"] = "password"
                bot.reply_to(message, "🔐 **Требуется двухфакторная аутентификация**\n\nВведите пароль от аккаунта Telegram:")
            else:
                bot.reply_to(message, f"❌ Ошибка при проверке кода: {error_msg[:150]}\nПопробуйте /login заново")
                auth_data["step"] = None
                auth_data["client"] = None
    
    elif auth_data["step"] == "password":
        auth_data["password"] = text
        
        try:
            bot.reply_to(message, "⏳ Проверка пароля...")
            
            auth_data["client"].sign_in(password=auth_data["password"])
            
            client = auth_data["client"]
            restart_engine_with_client()
            
            me = client.get_me()
            bot.reply_to(message, f"✅ **Успешный вход!**\n\n👤 Аккаунт: @{me.username or me.first_name}\n🆔 ID: {me.id}\n\nТеперь можно запускать рассылку через /startmail", parse_mode="Markdown")
            
            auth_data["step"] = None
            auth_data["client"] = None
            
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {str(e)[:150]}\nПопробуйте /login заново")
            auth_data["step"] = None
            auth_data["client"] = None

def restart_engine_with_client():
    global mailing_thread, CONFIG
    
    was_running = CONFIG["mailing_enabled"]
    
    if was_running:
        CONFIG["mailing_enabled"] = False
        time.sleep(2)
    
    if mailing_thread and mailing_thread.is_alive():
        pass
    else:
        mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
        mailing_thread.start()
    
    if was_running:
        time.sleep(3)
        CONFIG["mailing_enabled"] = True
        print("🔄 Движок перезапущен с новым клиентом")

# ==================== КОМАНДЫ БОТА ====================

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещен")
        return
    
    auth_status = "❌ Не авторизован"
    if client:
        try:
            me = client.get_me()
            auth_status = f"✅ @{me.username or me.first_name}"
        except:
            auth_status = "❌ Сессия устарела"
    
    info = f"""
🔐 **KORECKT V2.0 - УЛЬТИМАТИВНЫЙ РАССЫЛЬЩИК**

🔑 **Аккаунт:** {auth_status}

📋 **Управление:**
/login - Войти в аккаунт Telegram
/logout - Выйти из аккаунта
/add [текст] - Добавить объявление
/list - Список объявлений
/del [ID] - Удалить объявление
/clear - Очистить всё
/stats - Статистика
/chats - Список чатов

🚀 **Управление рассылкой:**
/startmail - ЗАПУСК рассылки
/stopmail - ОСТАНОВ рассылки

⚙️ **Настройка:**
/config - Текущие настройки
/setdelay [мин] [макс] - Паузы между чатами
/setround [мин] [макс] - Паузы между кругами

📊 **Текущий статус:** {'🟢 АКТИВНА' if CONFIG['mailing_enabled'] else '🔴 ОСТАНОВЛЕНА'}
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
    
    if client is None:
        bot.reply_to(msg, "❌ **Сначала войдите в аккаунт!**\n\nИспользуйте команду /login для авторизации")
        return
    
    try:
        client.get_me()
    except Exception as e:
        bot.reply_to(msg, f"❌ **Сессия устарела!**\nОшибка: {str(e)[:50]}\n\nИспользуйте /login для повторного входа")
        return
    
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "❌ Невозможно запустить: база пуста!\nДобавьте объявления через /add")
        return
    
    if not CONFIG["mailing_enabled"]:
        CONFIG["mailing_enabled"] = True
        bot.reply_to(msg, f"🚀 **РАССЫЛКА ЗАПУЩЕНА!**\n\n📝 Объявлений: {len(db.get_ads())}\n🎯 Чатов: {len(TARGET_CHATS)}\n⚙️ Статус: АКТИВНА")
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

# Обработчик для шагов авторизации
@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID and auth_data["step"] is not None)
def handle_auth_steps(msg):
    process_auth_step(msg)

# Запуск
if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT ULTIMATE V2.0 ДЛЯ RENDER")
    print("=" * 50)
    
    # Проверка переменных окружения
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не задан!")
    if not API_ID or not API_HASH:
        print("❌ ОШИБКА: API_ID или API_HASH не заданы!")
    if ADMIN_ID == 0:
        print("⚠️ ВНИМАНИЕ: ADMIN_ID не задан!")
    
    print(f"🤖 Бот токен: {'✅' if BOT_TOKEN else '❌'}")
    print(f"🔑 API данные: {'✅' if API_ID and API_HASH else '❌'}")
    print(f"👤 Admin ID: {ADMIN_ID if ADMIN_ID != 0 else '❌'}")
    print(f"🎯 Целевые чаты: {len(TARGET_CHATS)}")
    print("=" * 50)
    
    # Запуск движка
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()
    
    print("🤖 Бот запущен и готов к работе!")
    print("📱 Откройте Telegram и напишите /start")
    print("🔑 Для входа в аккаунт используйте /login")
    print("=" * 50)
    
    # Запуск бота с правильными параметрами
    while True:
        try:
            # Убираем все лишние параметры, оставляем только базовые
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка в polling: {e}")
            time.sleep(5)
