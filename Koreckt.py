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
import os  # Добавлен импорт os

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
    "delay_between_chats": {"min": 150, "max": 400},  # секунды
    "delay_between_rounds": {"min": 300, "max": 600},  # секунды
    "typing_speed": {"min": 5, "max": 12},  # символов в секунду
    "anti_flood": True,
    "smart_delays": True
}

bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_thread = None

# Данные для авторизации через бота
auth_sessions = {}  # {chat_id: {"step": "phone", "temp_client": None, "phone": None}}

# Эмуляция базы данных через JSON (чтобы не зависеть от SQLite)
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
        if len(self.data["history"]) > 1000:  # Храним последние 1000 записей
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
    """Умная задержка с прогрессом"""
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
    """Продвинутый расчет времени печати"""
    # Базовая скорость
    speed = random.uniform(CONFIG["typing_speed"]["min"], CONFIG["typing_speed"]["max"])
    base_time = len(text) / speed
    
    # Паузы на знаки препинания
    punctuation = text.count('.') * 0.25 + text.count(',') * 0.15 + text.count('!') * 0.2 + text.count('?') * 0.2
    punctuation += text.count('\n') * 0.5  # Новая строка
    
    # Сложные слова (капс, длинные слова)
    words = text.split()
    long_words = sum(1 for w in words if len(w) > 8)
    long_words_bonus = long_words * 0.3
    
    # Человеческий фактор (ошибки, раздумья)
    human_factor = random.uniform(0.85, 1.4)
    
    total = (base_time + punctuation + long_words_bonus) * human_factor
    
    # Лимиты
    return min(max(total, 2), 20)

def format_message_with_emoji(text):
    """Автоматическое добавление эмодзи для натуральности"""
    emojis = ["🔥", "💎", "⭐", "✅", "🚀", "💪", "🎯", "📢", "💡", "✨"]
    
    # С вероятностью 30% добавляем эмодзи в начало
    if random.random() < 0.3 and not any(e in text[:2] for e in emojis):
        emoji = random.choice(emojis)
        text = f"{emoji} {text}"
    
    return text

def pro_sender_engine():
    """Мощный движок рассылки"""
    global client
    
    print("🚀 KORECKT ENGINE V2.0 ЗАПУЩЕН")
    print("=" * 40)
    
    # Ждем авторизации через бота
    while client is None:
        print("⏳ Ожидание авторизации через бота...")
        time.sleep(5)
    
    print("✅ Юзербот успешно авторизован")
    try:
        print(f"👤 Аккаунт: {client.get_me().first_name}")
    except:
        print("⚠️ Не удалось получить информацию об аккаунте")
    
    print("=" * 40)
    
    while True:
        if not CONFIG["mailing_enabled"]:
            time.sleep(3)
            continue
        
        if client is None:
            print("⚠️ Клиент потерян, ожидание переподключения...")
            time.sleep(10)
            continue
        
        ads = db.get_ads()
        if not ads:
            print("📭 База объявлений пуста. Ожидание...")
            time.sleep(30)
            continue
        
        # Выбираем случайное объявление
        ad = random.choice(ads)
        ad_text = ad["text"]
        
        # Автоформатирование
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
            
            # Имитация входа в чат
            smart_delay(3, 8, "Имитация входа в чат")
            
            try:
                # Эмуляция набора текста
                print(f"✍️ Эмулируем набор текста...")
                typing_time = calculate_typing_time(ad_text)
                client(functions.messages.SetTypingRequest(
                    peer=chat,
                    action=types.SendMessageTypingAction()
                ))
                
                # Постепенная имитация печати (для реализма)
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
                
                # Отправка
                client.send_message(chat, ad_text)
                print(f"✅ УСПЕШНО ОТПРАВЛЕНО в {chat}")
                
                # Обновление статистики
                update_stats(True)
                db.add_history(ad["id"], chat, True)
                
                # Проверка дневного лимита
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
            
            # Пауза между чатами (кроме последнего)
            if idx < len(TARGET_CHATS) - 1:
                smart_delay(
                    CONFIG["delay_between_chats"]["min"],
                    CONFIG["delay_between_chats"]["max"],
                    "Пауза между чатами"
                )
        
        # Пауза между кругами
        if CONFIG["mailing_enabled"] and ads and client is not None:
            print(f"\n💤 КРУГ ЗАВЕРШЕН")
            
            # Адаптивная пауза (если много ошибок)
            if CONFIG["stats"]["errors"] > 10:
                wait_min, wait_max = 600, 900
                print("⚠️ Много ошибок, увеличиваю паузу")
            else:
                wait_min, wait_max = CONFIG["delay_between_rounds"]["min"], CONFIG["delay_between_rounds"]["max"]
            
            smart_delay(wait_min, wait_max, "Пауза между кругами")
            
            # Сброс счетчика ошибок
            if CONFIG["stats"]["errors"] > 0:
                CONFIG["stats"]["errors"] = max(0, CONFIG["stats"]["errors"] - 1)

# ==================== ФУНКЦИИ АВТОРИЗАЦИИ ЧЕРЕЗ БОТА ====================

@bot.message_handler(commands=['login'])
def login_cmd(message):
    """Начать авторизацию через бота"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Доступ запрещен")
        return
    
    if client is not None:
        bot.reply_to(message, "✅ Вы уже авторизованы! Используйте /logout для выхода")
        return
    
    # Создаем сессию для пользователя
    auth_sessions[message.chat.id] = {
        "step": "phone",
        "temp_client": None,
        "phone": None
    }
    
    bot.reply_to(message, "🔐 **Вход в аккаунт Telegram**\n\nВведите номер телефона в международном формате:\n`+71234567890`", parse_mode="Markdown")

@bot.message_handler(commands=['logout'])
def logout_cmd(message):
    """Выйти из аккаунта"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Доступ запрещен")
        return
    
    global client
    if client:
        try:
            client.disconnect()
        except:
            pass
        client = None
    
    bot.reply_to(message, "✅ Вы вышли из аккаунта Telegram")

@bot.message_handler(commands=['cancel'])
def cancel_auth_cmd(message):
    """Отменить авторизацию"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Доступ запрещен")
        return
    
    if message.chat.id in auth_sessions:
        if auth_sessions[message.chat.id]["temp_client"]:
            try:
                auth_sessions[message.chat.id]["temp_client"].disconnect()
            except:
                pass
        del auth_sessions[message.chat.id]
    
    bot.reply_to(message, "❌ Авторизация отменена")
    @bot.message_handler(func=lambda message: message.chat.id in auth_sessions)
def handle_auth_steps(message):
    """Обработка шагов авторизации"""
    global client
    
    chat_id = message.chat.id
    text = message.text.strip()
    session = auth_sessions[chat_id]
    
    if session["step"] == "phone":
        # Проверка формата телефона
        if not re.match(r'^\+?\d{10,15}$', text):
            bot.reply_to(message, "❌ Неверный формат. Пример: +71234567890\nПопробуйте снова или /cancel")
            return
        
        session["phone"] = text
        session["step"] = "code"
        
        try:
            # Создаем временный клиент
            temp_client = TelegramClient(f'temp_session_{chat_id}', API_ID, API_HASH)
            session["temp_client"] = temp_client
            
            bot.reply_to(message, "⏳ Отправка кода подтверждения...")
            temp_client.connect()
            temp_client.send_code_request(session["phone"])
            
            bot.reply_to(message, "📱 **Код подтверждения отправлен**\n\nВведите код из Telegram (только цифры):\n_Пример: 12345_", parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {str(e)[:100]}\nИспользуйте /login для новой попытки")
            del auth_sessions[chat_id]
    
    elif session["step"] == "code":
        # Проверка кода
        if not text.isdigit():
            bot.reply_to(message, "❌ Код должен содержать только цифры\nПопробуйте снова или /cancel")
            return
        
        try:
            bot.reply_to(message, "⏳ Проверка кода...")
            
            # Пробуем войти
            session["temp_client"].sign_in(session["phone"], text)
            
            # Успешный вход
            client = session["temp_client"]
            
            # Получаем информацию об аккаунте
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            
            bot.reply_to(message, f"✅ **Успешный вход!**\n\n👤 Аккаунт: {username}\n🆔 ID: {me.id}\n\nТеперь рассылка будет работать! Используйте /startmail для запуска", parse_mode="Markdown")
            
            # Очищаем сессию авторизации
            del auth_sessions[chat_id]
            
        except Exception as e:
            error_msg = str(e)
            
            # Проверка на 2FA
            if "2FA" in error_msg or "password" in error_msg.lower():
                session["step"] = "password"
                bot.reply_to(message, "🔐 **Требуется пароль 2FA**\n\nВведите пароль от аккаунта Telegram:")
            else:
                bot.reply_to(message, f"❌ Ошибка: {error_msg[:150]}\nИспользуйте /login для новой попытки")
                if session["temp_client"]:
                    try:
                        session["temp_client"].disconnect()
                    except:
                        pass
                del auth_sessions[chat_id]
    
    elif session["step"] == "password":
        try:
            bot.reply_to(message, "⏳ Проверка пароля...")
            
            session["temp_client"].sign_in(password=text)
            
            client = session["temp_client"]
            
            me = client.get_me()
            username = f"@{me.username}" if me.username else me.first_name
            
            bot.reply_to(message, f"✅ **Успешный вход!**\n\n👤 Аккаунт: {username}\n🆔 ID: {me.id}\n\nТеперь рассылка будет работать! Используйте /startmail для запуска", parse_mode="Markdown")
            
            del auth_sessions[chat_id]
            
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {str(e)[:150]}\nИспользуйте /login для новой попытки")
            if session["temp_client"]:
                try:
                    session["temp_client"].disconnect()
                except:
                    pass
            del auth_sessions[chat_id]

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

🔑 **Статус аккаунта:** {auth_status}

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
    for ad in ads[-10:]:  # Показываем последние 10
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
        bot.reply_to(msg, "❌ **Сначала войдите в аккаунт!**\n\nИспользуйте /login для авторизации")
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

# Запуск
if __name__ == "__main__":
    print("=" * 50)
    print("🔥 KORECKT ULTIMATE V2.0 ДЛЯ RENDER")
    print("=" * 50)
    
    # Запуск движка в отдельном потоке (будет ждать авторизации)
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()
    
    print("🤖 Бот запущен и готов к работе!")
    print(f"👤 Ваш ID: {ADMIN_ID}")
    print("📱 Откройте Telegram и напишите /start")
    print("🔑 Для входа в аккаунт используйте /login")
    print("=" * 50)
    
    # Запуск бота
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
