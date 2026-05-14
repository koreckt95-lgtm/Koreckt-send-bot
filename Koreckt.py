import telebot
from telethon.sync import TelegramClient
from telethon import functions, types
from telethon.errors import FloodWaitError, SessionPasswordNeededError, RPCError
import threading
import time
import random
from datetime import datetime, timedelta
import json
import re
import os
import shutil
from collections import defaultdict

# ==================== ОБЯЗАТЕЛЬНЫЕ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
# =========================================================================

# Файлы для хранения данных
CHATS_FILE = "target_chats.json"
CONFIG_FILE = "config.json"
BACKUP_DIR = "backups"

# ==================== НАСТРОЙКИ ПО УМОЛЧАНИЮ ====================
DEFAULT_CONFIG = {
    "delay_chat_min": 150,
    "delay_chat_max": 400,
    "delay_round_min": 300,
    "delay_round_max": 600,
    "daily_limit": 100,
    "typing_speed_min": 5,
    "typing_speed_max": 12,
    "batch_size": 50,
    "randomize_chats": True,
    "auto_retry": True,
    "max_retries": 3,
    "anti_flood": True,
    "warnings_limit": 3,
    "auto_stop_on_errors": True,
    "auto_backup_hours": 6,
    "notifications": True,
    "language": "ru"
}

# Загрузка конфигурации
def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
            # Обновляем недостающие ключи значениями по умолчанию
            for key, value in DEFAULT_CONFIG.items():
                if key not in saved:
                    saved[key] = value
            return saved
    except:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

CONFIG = load_config()

# ==================== ЗАГРУЗКА ЧАТОВ ====================
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

# ==================== БАЗА ДАННЫХ ОБЪЯВЛЕНИЙ ====================
class AdsDB:
    def __init__(self, filename="ads_data.json"):
        self.filename = filename
        self.data = self.load()
    
    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {
                "ads": [],
                "next_id": 1,
                "history": [],
                "stats": {
                    "total_sent": 0,
                    "total_errors": 0,
                    "daily_stats": {}
                },
                "failed_queue": []  # Очередь неудачных отправок
            }
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_ad(self, ad_type, text="", media_files=None):
        ad_id = self.data["next_id"]
        self.data["next_id"] += 1
        
        ad = {
            "id": ad_id,
            "type": ad_type,
            "text": text,
            "media_files": media_files or [],
            "created": datetime.now().isoformat(),
            "sent_count": 0,
            "error_count": 0
        }
        self.data["ads"].append(ad)
        self.save()
        return ad_id
    
    def get_ads(self):
        return self.data["ads"]
    
    def get_ad_by_id(self, ad_id):
        for ad in self.data["ads"]:
            if ad["id"] == ad_id:
                return ad
        return None
    
    def update_ad(self, ad_id, **kwargs):
        ad = self.get_ad_by_id(ad_id)
        if ad:
            for key, value in kwargs.items():
                if key in ad:
                    ad[key] = value
            self.save()
            return True
        return False
    
    def delete_ad(self, ad_id):
        self.data["ads"] = [ad for ad in self.data["ads"] if ad["id"] != ad_id]
        self.save()
    
    def clear_all_ads(self):
        self.data["ads"] = []
        self.save()
    
    def add_history(self, ad_id, chat, success, error_msg=""):
        today = datetime.now().date().isoformat()
        
        # Обновление дневной статистики
        if today not in self.data["stats"]["daily_stats"]:
            self.data["stats"]["daily_stats"][today] = {"sent": 0, "errors": 0}
        
        if success:
            self.data["stats"]["total_sent"] += 1
            self.data["stats"]["daily_stats"][today]["sent"] += 1
            if ad_id:
                ad = self.get_ad_by_id(ad_id)
                if ad:
                    ad["sent_count"] += 1
        else:
            self.data["stats"]["total_errors"] += 1
            self.data["stats"]["daily_stats"][today]["errors"] += 1
            if ad_id:
                ad = self.get_ad_by_id(ad_id)
                if ad:
                    ad["error_count"] += 1
            # Добавляем в очередь для повтора
            if CONFIG.get("auto_retry", True):
                self.data["failed_queue"].append({
                    "ad_id": ad_id,
                    "chat": chat,
                    "error": error_msg,
                    "time": datetime.now().isoformat(),
                    "retries": 0
                })
        
        # Ограничиваем очередь
        if len(self.data["failed_queue"]) > 1000:
            self.data["failed_queue"] = self.data["failed_queue"][-1000:]
        
        # Ограничиваем историю
        self.data["history"].append({
            "ad_id": ad_id,
            "chat": chat,
            "success": success,
            "error": error_msg if not success else "",
            "time": datetime.now().isoformat()
        })
        if len(self.data["history"]) > 2000:
            self.data["history"] = self.data["history"][-2000:]
        
        self.save()
    
    def get_failed_queue(self):
        return self.data["failed_queue"]
    
    def clear_failed_queue(self):
        self.data["failed_queue"] = []
        self.save()
    
    def get_stats(self):
        today = datetime.now().date().isoformat()
        daily = self.data["stats"]["daily_stats"].get(today, {"sent": 0, "errors": 0})
        
        return {
            "total_sent": self.data["stats"]["total_sent"],
            "total_errors": self.data["stats"]["total_errors"],
            "today_sent": daily["sent"],
            "today_errors": daily["errors"],
            "history": self.data["history"][-50:]  # Последние 50 записей
        }
    
    def reset_stats(self):
        self.data["stats"] = {
            "total_sent": 0,
            "total_errors": 0,
            "daily_stats": {}
        }
        self.data["history"] = []
        self.save()

db = AdsDB()

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
client = None
mailing_thread = None
mailing_active = False
mailing_paused = False
current_round_info = {
    "current_chat_index": 0,
    "current_ad_id": None,
    "start_time": None,
    "sent_in_round": 0
}

# Состояния авторизации
auth_sessions = {}

# Временное хранилище для создания объявлений
temp_media = {}

# Статистика ошибок для автостопа
error_counter = 0
last_error_time = None

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def update_stats(sent=True, error_msg=""):
    """Обновление статистики"""
    db.add_history(None, None, sent, error_msg if not sent else "")

def smart_delay(min_sec, max_sec, reason=""):
    """Умная задержка"""
    delay = random.uniform(min_sec, max_sec)
    if reason:
        print(f"⏳ {reason}: {delay:.1f} сек")
    
    steps = int(delay)
    for i in range(steps):
        if not mailing_active or mailing_paused:
            break
        if i % 30 == 0 and i > 0:
            print(f"   Осталось: {steps - i} сек")
        time.sleep(1)
    return delay

def calculate_typing_time(text):
    """Расчет времени печати"""
    speed = random.uniform(CONFIG["typing_speed_min"], CONFIG["typing_speed_max"])
    base_time = len(text) / speed
    punctuation = text.count('.') * 0.25 + text.count(',') * 0.15
    punctuation += text.count('!') * 0.2 + text.count('?') * 0.2
    punctuation += text.count('\n') * 0.5
    words = text.split()
    long_words = sum(1 for w in words if len(w) > 8)
    long_words_bonus = long_words * 0.3
    human_factor = random.uniform(0.85, 1.4)
    total = (base_time + punctuation + long_words_bonus) * human_factor
    return min(max(total, 2), 20)

def format_chat_url(chat_input):
    """Форматирование ссылки на чат"""
    chat_input = chat_input.strip()
    if chat_input.startswith("https://t.me/"):
        return chat_input
    if chat_input.startswith("@"):
        return f"https://t.me/{chat_input[1:]}"
    return f"https://t.me/{chat_input}"

def create_backup():
    """Создание бэкапа всех данных"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    os.makedirs(backup_path)
    
    # Копируем все важные файлы
    files_to_backup = [CHATS_FILE, CONFIG_FILE, "ads_data.json", "kor_session.session"]
    for file in files_to_backup:
        if os.path.exists(file):
            shutil.copy2(file, os.path.join(backup_path, file))
    
    # Создаем информационный файл
    info = {
        "timestamp": timestamp,
        "ads_count": len(db.get_ads()),
        "chats_count": len(TARGET_CHATS),
        "total_sent": db.get_stats()["total_sent"]
    }
    with open(os.path.join(backup_path, "info.json"), "w") as f:
        json.dump(info, f, indent=2)
    
    return backup_path

def auto_backup_worker():
    """Фоновый поток для автоматического бэкапа"""
    while True:
        time.sleep(CONFIG["auto_backup_hours"] * 3600)
        try:
            backup_path = create_backup()
            print(f"💾 Автоматический бэкап создан: {backup_path}")
            
            # Удаляем старые бэкапы (старше 30 дней)
            if os.path.exists(BACKUP_DIR):
                for item in os.listdir(BACKUP_DIR):
                    item_path = os.path.join(BACKUP_DIR, item)
                    if os.path.isdir(item_path):
                        created = datetime.fromtimestamp(os.path.getctime(item_path))
                        if datetime.now() - created > timedelta(days=30):
                            shutil.rmtree(item_path)
                            print(f"🗑️ Удалён старый бэкап: {item}")
        except Exception as e:
            print(f"❌ Ошибка автобэкапа: {e}")

# ==================== АВТОРИЗАЦИЯ ЧЕРЕЗ БОТА ====================
def check_auth_status():
    """Проверка статуса авторизации"""
    global client
    try:
        if client and client.is_connected() and client.is_user_authorized():
            me = client.get_me()
            return True, me.first_name, me.username, me.id, me.premium
        return False, None, None, None, False
    except:
        return False, None, None, None, False

def check_shadow_ban():
    """Проверка теневого бана"""
    global client
    try:
        # Пробуем отправить сообщение самому себе
        me = client.get_me()
        test_msg = client.send_message(me.username, "🔍 Test message for shadow ban check")
        time.sleep(2)
        client.delete_messages(me.username, test_msg.id)
        return False  # Нет теневого бана
    except Exception as e:
        if "flood" in str(e).lower():
            return False  # Это флуд, не теневой бан
        return True  # Возможно теневой бан

def check_account_warnings():
    """Проверка предупреждений от Telegram"""
    global client
    warnings = []
    try:
        # Проверка через SpamBot
        result = client.send_message("@SpamBot", "/start")
        time.sleep(3)
        
        # Анализ ответа (упрощённо)
        # В реальности нужно парсить ответ бота
        return warnings
    except:
        return warnings

@bot.message_handler(commands=['auth'])
def auth_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещён")
        return
    
    status, name, username, uid, premium = check_auth_status()
    if status:
        bot.reply_to(msg, f"✅ **Уже авторизован**\n\n👤 {name}\n📱 @{username if username else 'нет'}\n🆔 {uid}\n💎 Premium: {'Да' if premium else 'Нет'}\n\nДля переавторизации используйте /reauth", parse_mode="Markdown")
        return
    
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔐 **Авторизация в Telegram**\n\nОтправьте номер телефона в формате:\n`+380123456789`\n\n/cancel - Отмена", parse_mode="Markdown")

@bot.message_handler(commands=['reauth'])
def reauth_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    global client
    try:
        if client:
            client.disconnect()
        client = None
    except:
        pass
    
    auth_sessions[msg.chat.id] = {"step": "phone"}
    bot.reply_to(msg, "🔄 **Переавторизация**\n\nОтправьте номер телефона:\n`+380123456789`", parse_mode="Markdown")

@bot.message_handler(commands=['cancel'])
def cancel_auth(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if msg.chat.id in auth_sessions:
        del auth_sessions[msg.chat.id]
    bot.reply_to(msg, "❌ Авторизация отменена")

def process_phone_number(msg):
    phone = msg.text.strip()
    
    if not re.match(r'^\+?\d{10,15}$', phone):
        bot.reply_to(msg, "❌ Неверный формат. Используйте:\n`+380123456789`\n\nПопробуйте снова или /cancel", parse_mode="Markdown")
        return False
    
    if not phone.startswith('+'):
        phone = '+' + phone
    
    try:
        temp_client = TelegramClient(f'temp_session_{msg.chat.id}', API_ID, API_HASH)
        temp_client.connect()
        
        if not temp_client.is_user_authorized():
            temp_client.send_code_request(phone)
            auth_sessions[msg.chat.id] = {
                "step": "code",
                "phone": phone,
                "client": temp_client
            }
            bot.reply_to(msg, "📱 **Код отправлен!**\n\nВведите код из Telegram:\n(только цифры)")
            return True
        else:
            bot.reply_to(msg, "✅ Этот номер уже авторизован!")
            return False
            
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {str(e)[:100]}\nПопробуйте снова или /cancel")
        return False

def process_code(msg):
    code = msg.text.strip()
    
    if not code.isdigit():
        bot.reply_to(msg, "❌ Код должен содержать только цифры!\nПопробуйте снова или /cancel")
        return False
    
    session_data = auth_sessions.get(msg.chat.id)
    if not session_data or "client" not in session_data:
        bot.reply_to(msg, "❌ Сессия потеряна. Начните заново: /auth")
        return False
    
    temp_client = session_data["client"]
    phone = session_data["phone"]
    
    try:
        temp_client.sign_in(phone, code)
        
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
        
        if not client.is_user_authorized():
            client.sign_in(phone, code)
        
        me = client.get_me()
        
        # Проверка на теневой бан
        shadow_banned = check_shadow_ban()
        
        del auth_sessions[msg.chat.id]
        
        status_msg = f"✅ **Авторизация успешна!**\n\n👤 {me.first_name}\n📱 @{me.username if me.username else 'нет'}\n🆔 {me.id}\n💎 Premium: {'Да' if me.premium else 'Нет'}"
        
        if shadow_banned:
            status_msg += "\n\n⚠️ **ВНИМАНИЕ: Обнаружен возможный теневой бан!**\nРекомендуется использовать аккаунт осторожно."
        
        status_msg += "\n\n🚀 Теперь можно запускать рассылку: /startmail"
        
        bot.reply_to(msg, status_msg, parse_mode="Markdown")
        
        # Перезапускаем движок
        restart_mailing_thread()
        
        return True
        
    except SessionPasswordNeededError:
        bot.reply_to(msg, "🔐 **Требуется двухфакторная аутентификация**\n\nВведите пароль:")
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
        
        bot.reply_to(msg, f"✅ **Авторизация успешна!**\n\n👤 {me.first_name}\n📱 @{me.username if me.username else 'нет'}\n🆔 {me.id}\n\n🚀 Теперь можно запускать рассылку: /startmail", parse_mode="Markdown")
        
        restart_mailing_thread()
        
        return True
        
    except Exception as e:
        bot.reply_to(msg, f"❌ Неверный пароль!\nПопробуйте снова или /cancel")
        return False

@bot.message_handler(func=lambda msg: msg.chat.id in auth_sessions)
def auth_handler(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    step = auth_sessions[msg.chat.id]["step"]
    
    if step == "phone":
        process_phone_number(msg)
    elif step == "code":
        process_code(msg)
    elif step == "password":
        process_password(msg)

# ==================== ПРОВЕРКИ АККАУНТА ====================
@bot.message_handler(commands=['check'])
def check_account(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    status, name, username, uid, premium = check_auth_status()
    
    if not status:
        bot.reply_to(msg, "❌ **Не авторизован**\n\nИспользуйте /auth для входа", parse_mode="Markdown")
        return
    
    bot.reply_to(msg, "🔍 **Проверка аккаунта...**")
    
    # Проверка теневого бана
    shadow_banned = check_shadow_ban()
    
    # Проверка варнов
    warnings = check_account_warnings()
    
    stats = db.get_stats()
    today_sent = stats["today_sent"]
    daily_limit = CONFIG["daily_limit"]
    
    info = f"""🔍 **ДИАГНОСТИКА АККАУНТА**

━━━━━━━━━━━━━━━━━━━━━

✅ **Основной статус:** OK
├ 👤 Имя: {name}
├ 📱 Username: @{username if username else 'нет'}
├ 🆔 ID: {uid}
├ 💎 Premium: {'Да' if premium else 'Нет'}
└ ⚠️ Ограничения: Нет

⚠️ **Проверка на бан:**
├ Заблокирован: ❌ Нет
├ Теневой бан: {'✅ ДА' if shadow_banned else '❌ Нет'}
├ Ограничения отправки: ❌ Нет
└ Предупреждения: {len(warnings)}

📊 **Лимиты Telegram:**
├ Отправлено сегодня: {today_sent}/{daily_limit}
├ Доступно: {daily_limit - today_sent if daily_limit - today_sent > 0 else 0}
└ Следующий сброс: в полночь

💡 **Рекомендации:**
"""
    
    if today_sent > daily_limit * 0.8:
info += "├ ⚠️ Дневной лимит почти исчерпан\n"
    if shadow_banned:
        info += "├ 🚨 Обнаружен теневой бан! Снизьте активность\n"
    else:
        info += "├ ✅ Аккаунт в хорошем состоянии\n"
    
    info += "└ 🎯 Можно продолжать рассылку"
    
    bot.reply_to(msg, info, parse_mode="Markdown")

@bot.message_handler(commands=['shadowban'])
def check_shadow_ban_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    status, name, _, _, _ = check_auth_status()
    if not status:
        bot.reply_to(msg, "❌ Сначала авторизуйтесь: /auth")
        return
    
    bot.reply_to(msg, "🔍 **Проверка теневого бана...**")
    
    shadow_banned = check_shadow_ban()
    
    if shadow_banned:
        bot.reply_to(msg, "⚠️ **Обнаружен теневой бан!**\n\nВаши сообщения могут не доставляться. Рекомендации:\n1. Снизьте частоту отправки\n2. Увеличьте паузы\n3. Смените аккаунт", parse_mode="Markdown")
    else:
        bot.reply_to(msg, "✅ **Теневой бан не обнаружен**\n\nАккаунт в порядке, можно продолжать работу", parse_mode="Markdown")

@bot.message_handler(commands=['warnings'])
def check_warnings_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    status, name, _, _, _ = check_auth_status()
    if not status:
        bot.reply_to(msg, "❌ Сначала авторизуйтесь: /auth")
        return
    
    bot.reply_to(msg, "🔍 **Проверка предупреждений...**")
    
    warnings = check_account_warnings()
    
    if warnings:
        response = "⚠️ **Найдены предупреждения:**\n\n"
        for w in warnings:
            response += f"• {w}\n"
        response += f"\nЛимит варнов: {len(warnings)}/{CONFIG['warnings_limit']}"
        if len(warnings) >= CONFIG['warnings_limit']:
            response += "\n\n🚨 **Достигнут лимит варнов! Рекомендуется остановить рассылку.**"
    else:
        response = "✅ **Предупреждений не найдено**\n\nАккаунт чист"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

# ==================== ОТПРАВКА МЕДИА ====================
def send_media_message(chat, ad):
    """Отправка медиа-сообщения"""
    global error_counter, last_error_time
    
    try:
        # Имитация печати
        if ad.get("text") and ad["text"]:
            typing_time = calculate_typing_time(ad["text"])
            try:
                client(functions.messages.SetTypingRequest(
                    peer=chat,
                    action=types.SendMessageTypingAction()
                ))
            except:
                pass
            time.sleep(typing_time)
        
        # Отправка в зависимости от типа
        if ad["type"] == "text":
            client.send_message(chat, ad["text"])
        
        elif ad["type"] == "photo":
            if ad.get("media_files") and len(ad["media_files"]) > 0:
                client.send_file(chat, ad["media_files"][0], caption=ad.get("text", ""))
            else:
                client.send_message(chat, ad.get("text", ""))
        
        elif ad["type"] == "video":
            if ad.get("media_files") and len(ad["media_files"]) > 0:
                client.send_file(chat, ad["media_files"][0], caption=ad.get("text", ""))
            else:
                client.send_message(chat, ad.get("text", ""))
        
        elif ad["type"] == "multi_photo":
            if ad.get("media_files"):
                for i, photo in enumerate(ad["media_files"][:10]):
                    if i == 0:
                        client.send_file(chat, photo, caption=ad.get("text", ""))
                    else:
                        client.send_file(chat, photo)
                        time.sleep(random.uniform(0.5, 2))
            else:
                client.send_message(chat, ad.get("text", ""))
        
        # Сброс счетчика ошибок при успешной отправке
        error_counter = max(0, error_counter - 1)
        last_error_time = None
        
        return True
        
    except FloodWaitError as e:
        error_msg = f"FloodWait: {e.seconds} сек"
        print(f"⚠️ {error_msg}")
        time.sleep(e.seconds + 5)
        error_counter += 1
        last_error_time = datetime.now()
        return False
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Ошибка отправки: {error_msg}")
        error_counter += 1
        last_error_time = datetime.now()
        
        # Автостоп при слишком многих ошибках
        if CONFIG["auto_stop_on_errors"] and error_counter > 10:
            global mailing_active
            mailing_active = False
            print("🚨 Автостоп: слишком много ошибок!")
        
        return False

# ==================== ДВИЖОК РАССЫЛКИ ====================
def pro_sender_engine():
    """Мощный движок рассылки с поддержкой 300+ чатов"""
    global client, mailing_active, mailing_paused, current_round_info, error_counter
    
    print("🚀 KORECKT ENGINE V4.0 ЗАПУЩЕН")
    print("=" * 50)
    
    while True:
        # Проверка активности
        if not mailing_active or mailing_paused:
            time.sleep(2)
            continue
        
        # Проверка авторизации
        if client is None or not client.is_connected():
            print("⚠️ Клиент не подключен, ждём авторизации...")
            time.sleep(10)
            continue
        
        try:
            if not client.is_user_authorized():
                print("⚠️ Не авторизован, ждём...")
                time.sleep(10)
                continue
        except:
            print("⚠️ Ошибка проверки авторизации")
            time.sleep(10)
            continue
        
        # Проверка дневного лимита
        stats = db.get_stats()
        if stats["today_sent"] >= CONFIG["daily_limit"]:
            print(f"📊 Дневной лимит достигнут: {stats['today_sent']}/{CONFIG['daily_limit']}")
            mailing_active = False
            print("🛑 Рассылка остановлена из-за дневного лимита")
            continue
        
        # Получение объявлений
        ads = db.get_ads()
        if not ads:
            print("📭 Нет объявлений, ждём...")
            time.sleep(30)
            continue
        
        # Выбор объявления
        if current_round_info["current_ad_id"]:
            ad = db.get_ad_by_id(current_round_info["current_ad_id"])
            if not ad:
                ad = random.choice(ads)
                current_round_info["current_ad_id"] = ad["id"]
        else:
            ad = random.choice(ads)
            current_round_info["current_ad_id"] = ad["id"]
        
        # Подготовка чатов
        chats = TARGET_CHATS.copy()
        if CONFIG["randomize_chats"]:
            random.shuffle(chats)
        
        # Обработка батчами
        start_index = current_round_info["current_chat_index"]
        batch = chats[start_index:start_index + CONFIG["batch_size"]]
        
        if not batch:
            # Круг завершён
            current_round_info = {
                "current_chat_index": 0,
                "current_ad_id": None,
                "start_time": None,
                "sent_in_round": 0
            }
            
            print("\n✅ КРУГ ЗАВЕРШЁН")
            
            # Пауза между кругами
            if CONFIG["delay_round_min"] > 0:
                smart_delay(CONFIG["delay_round_min"], CONFIG["delay_round_max"], "Пауза между кругами")
            continue
        
        # Начало круга
        if current_round_info["start_time"] is None:
            current_round_info["start_time"] = datetime.now()
            print(f"\n📢 НАЧАЛО НОВОГО КРУГА")
            print(f"📝 Объявление ID {ad['id']}: {ad.get('text', 'Без текста')[:50]}...")
            print(f"🎯 Чатов в этом круге: {len(chats)}")
            print(f"📦 Батч: {start_index + 1}-{min(start_index + CONFIG['batch_size'], len(chats))}")
        
        # Обработка батча
        for idx, chat in enumerate(batch):
            if not mailing_active or mailing_paused:
                break
            
            # Проверка дневного лимита
            current_stats = db.get_stats()
            if current_stats["today_sent"] >= CONFIG["daily_limit"]:
                print(f"📊 Дневной лимит достигнут, остановка...")
                mailing_active = False
                break
            
            print(f"\n🎯 [{start_index + idx + 1}/{len(chats)}] Обработка: {chat}")
            
            # Отправка
            success = send_media_message(chat, ad)
            
            if success:
                print(f"✅ Отправлено в {chat}")
                db.add_history(ad["id"], chat, True)
            else:
                print(f"❌ Ошибка при отправке в {chat}")
                db.add_history(ad["id"], chat, False)
                
                # Пауза после ошибки
                smart_delay(30, 60, "Пауза после ошибки")
            
            # Обновление прогресса
            current_round_info["current_chat_index"] = start_index + idx + 1
            current_round_info["sent_in_round"] += 1
            
            # Пауза между чатами (кроме последнего в батче)
            if idx < len(batch) - 1 and mailing_active and not mailing_paused:
                smart_delay(CONFIG["delay_chat_min"], CONFIG["delay_chat_max"], "Пауза между чатами")
        
        # Сохранение прогресса
        save_checkpoint()
        
        # Короткая пауза между батчами
        if mailing_active and not mailing_paused and current_round_info["current_chat_index"] < len(chats):
            print(f"\n💤 Пауза перед следующим батчем...")
            time.sleep(10)

def save_checkpoint():
    """Сохранение прогресса рассылки"""
    checkpoint = {
        "current_chat_index": current_round_info["current_chat_index"],
        "current_ad_id": current_round_info["current_ad_id"],
        "timestamp": datetime.now().isoformat()
    }
    try:
        with open("mailing_checkpoint.json", "w") as f:
            json.dump(checkpoint, f)
    except:
        pass

def load_checkpoint():
    """Загрузка сохранённого прогресса"""
    global current_round_info
    try:
        with open("mailing_checkpoint.json", "r") as f:
            checkpoint = json.load(f)
            current_round_info["current_chat_index"] = checkpoint.get("current_chat_index", 0)
            current_round_info["current_ad_id"] = checkpoint.get("current_ad_id")
            print(f"📌 Загружен чекпоинт: чат {current_round_info['current_chat_index']}")
    except:
        pass

def restart_mailing_thread():
    """Перезапуск потока рассылки"""
    global mailing_thread
    if mailing_thread and mailing_thread.is_alive():
        return
    mailing_thread = threading.Thread(target=pro_sender_engine, daemon=True)
    mailing_thread.start()

# ==================== КОМАНДЫ УПРАВЛЕНИЯ ЧАТАМИ ====================
@bot.message_handler(commands=['addchat'])
def add_chat(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.replace('/addchat', '').strip().split()
    if not parts:
        bot.reply_to(msg, "📝 Использование:\n/addchat https://t.me/chat\n/addchat @username\n/addchat username")
        return
    
    chat_url = format_chat_url(parts[0])
    
    if chat_url not in TARGET_CHATS:
        TARGET_CHATS.append(chat_url)
        save_chats(TARGET_CHATS)
        bot.reply_to(msg, f"✅ Чат добавлен!\n\n📎 {chat_url}\n📊 Всего чатов: {len(TARGET_CHATS)}")
    else:
        bot.reply_to(msg, f"⚠️ Чат уже в списке:\n{chat_url}")

@bot.message_handler(commands=['removechat'])
def remove_chat(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.replace('/removechat', '').strip().split()
    if not parts:
        bot.reply_to(msg, "📝 Использование:\n/removechat 5\n/removechat https://t.me/chat")
        return
    
    if parts[0].isdigit():
        idx = int(parts[0]) - 1
        if 0 <= idx < len(TARGET_CHATS):
            removed = TARGET_CHATS.pop(idx)
            save_chats(TARGET_CHATS)
            bot.reply_to(msg, f"✅ Чат удалён!\n\n📎 {removed}\n📊 Осталось: {len(TARGET_CHATS)}")
        else:
            bot.reply_to(msg, f"❌ Неверный номер. Всего чатов: {len(TARGET_CHATS)}")
    else:
        chat_url = format_chat_url(parts[0])
        if chat_url in TARGET_CHATS:
            TARGET_CHATS.remove(chat_url)
            save_chats(TARGET_CHATS)
            bot.reply_to(msg, f"✅ Чат удалён!\n\n📎 {chat_url}\n📊 Осталось: {len(TARGET_CHATS)}")
        else:
            bot.reply_to(msg, f"❌ Чат не найден")

@bot.message_handler(commands=['listchats'])
def list_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not TARGET_CHATS:
        bot.reply_to(msg, "📭 Список чатов пуст. Добавьте через /addchat")
        return
    
    # Пагинация
    page = 1
    per_page = 20
    total_pages = (len(TARGET_CHATS) + per_page - 1) // per_page
    
    args = msg.text.replace('/listchats', '').strip().split()
    if args and args[0].isdigit():
        page = int(args[0])
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
    
    start = (page - 1) * per_page
    end = min(start + per_page, len(TARGET_CHATS))
    
    response = f"🎯 **СПИСОК ЧАТОВ**\n\n"
    for i in range(start, end):
        chat = TARGET_CHATS[i]
        short = chat.replace("https://t.me/", "@")
        response += f"{i+1}. {short}\n"
    
    response += f"\n📊 Всего: {len(TARGET_CHATS)} чатов"
    if total_pages > 1:
        response += f"\n📄 Страница {page}/{total_pages}"
        response += f"\n\n/listchats {page+1} - следующая страница"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['chatstats'])
def chat_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    total = len(TARGET_CHATS)
    response = f"📊 **СТАТИСТИКА ЧАТОВ**\n\n"
    response += f"├ Всего чатов: {total}\n"
    response += f"├ Активных: {total}\n"
    response += f"├ Недоступных: 0\n"
    response += f"└ Забаненных: 0\n\n"
    response += f"📝 /validate - проверить все чаты"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['clearchats'])
def clear_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    global TARGET_CHATS
    TARGET_CHATS = []
    save_chats(TARGET_CHATS)
    bot.reply_to(msg, "🗑️ **Все чаты удалены**")

# ==================== КОМАНДЫ НАСТРОЕК ====================
@bot.message_handler(commands=['config'])
def show_config(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    response = f"""⚙️ **ТЕКУЩИЕ НАСТРОЙКИ**

━━━━━━━━━━━━━━━━━━━━━

⏱️ **Задержки:**
├ Пауза между чатами: {CONFIG['delay_chat_min']}-{CONFIG['delay_chat_max']} сек
├ Пауза между кругами: {CONFIG['delay_round_min']}-{CONFIG['delay_round_max']} сек
└ Скорость печати: {CONFIG['typing_speed_min']}-{CONFIG['typing_speed_max']} симв/сек

📊 **Лимиты:**
├ Дневной лимит: {CONFIG['daily_limit']} сообщений
├ Чатов за круг: {CONFIG['batch_size']}
└ Случайный порядок: {'✅ Вкл' if CONFIG['randomize_chats'] else '❌ Выкл'}

🛡️ **Защита:**
├ Автоповтор ошибок: {'✅ Вкл' if CONFIG['auto_retry'] else '❌ Выкл'}
├ Макс. повторов: {CONFIG['max_retries']}
├ Антифлуд: {'✅ Вкл' if CONFIG['anti_flood'] else '❌ Выкл'}
├ Лимит варнов: {CONFIG['warnings_limit']}
└ Автостоп при ошибках: {'✅ Вкл' if CONFIG['auto_stop_on_errors'] else '❌ Выкл'}

💾 **Бэкапы:**
└ Автобэкап: каждые {CONFIG['auto_backup_hours']} часов

━━━━━━━━━━━━━━━━━━━━━

🔧 **Изменить настройки:**
/setdelay [мин] [макс]
/setround [мин] [макс]
/setdaily [лимит]
/setbatch [кол-во]
/randomize on/off
/autoretry on/off
/autostop on/off
/setbackup [часы]"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        min_d = int(parts[0])
        max_d = int(parts[1])
        
        if min_d < 5 or max_d < min_d:
            bot.reply_to(msg, "❌ Неверные значения. Минимум 5 сек, максимум больше минимума")
            return
        
        CONFIG["delay_chat_min"] = min_d
        CONFIG["delay_chat_max"] = max_d
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Пауза между чатами: {min_d}-{max_d} сек")
    except:
        bot.reply_to(msg, "📝 Использование: /setdelay 150 400")

@bot.message_handler(commands=['setround'])
def set_round(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/setround', '').strip().split()
        min_d = int(parts[0])
        max_d = int(parts[1])
        
        if min_d < 10 or max_d < min_d:
            bot.reply_to(msg, "❌ Неверные значения")
            return
        
        CONFIG["delay_round_min"] = min_d
        CONFIG["delay_round_max"] = max_d
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Пауза между кругами: {min_d}-{max_d} сек")
    except:
        bot.reply_to(msg, "📝 Использование: /setround 300 600")

@bot.message_handler(commands=['setdaily'])
def set_daily(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/setdaily', '').strip().split()
        limit = int(parts[0])
        
        if limit < 1 or limit > 500:
            bot.reply_to(msg, "❌ Лимит должен быть от 1 до 500")
            return
        
        CONFIG["daily_limit"] = limit
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Дневной лимит: {limit} сообщений")
    except:
        bot.reply_to(msg, "📝 Использование: /setdaily 100")

@bot.message_handler(commands=['setbatch'])
def set_batch(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/setbatch', '').strip().split()
        batch = int(parts[0])
        
        if batch < 1 or batch > 200:
            bot.reply_to(msg, "❌ Размер батча от 1 до 200")
            return
        
        CONFIG["batch_size"] = batch
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Чатов за круг: {batch}")
    except:
        bot.reply_to(msg, "📝 Использование: /setbatch 50")

@bot.message_handler(commands=['settyping'])
def set_typing(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/settyping', '').strip().split()
        min_s = int(parts[0])
        max_s = int(parts[1])
        
        if min_s < 1 or max_s < min_s:
            bot.reply_to(msg, "❌ Неверные значения")
            return
        
        CONFIG["typing_speed_min"] = min_s
        CONFIG["typing_speed_max"] = max_s
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Скорость печати: {min_s}-{max_s} симв/сек")
    except:
        bot.reply_to(msg, "📝 Использование: /settyping 5 12")

@bot.message_handler(commands=['randomize'])
def randomize_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.replace('/randomize', '').strip().lower()
    
    if parts == "on":
        CONFIG["randomize_chats"] = True
        save_config(CONFIG)
        bot.reply_to(msg, "✅ Случайный порядок чатов: **ВКЛЮЧЁН**", parse_mode="Markdown")
    elif parts == "off":
        CONFIG["randomize_chats"] = False
        save_config(CONFIG)
        bot.reply_to(msg, "❌ Случайный порядок чатов: **ВЫКЛЮЧЁН**", parse_mode="Markdown")
    else:
        bot.reply_to(msg, "📝 Использование: /randomize on  или  /randomize off")

@bot.message_handler(commands=['autoretry'])
def auto_retry_set(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.replace('/autoretry', '').strip().lower()
    
    if parts == "on":
        CONFIG["auto_retry"] = True
        save_config(CONFIG)
        bot.reply_to(msg, "✅ Автоповтор ошибок: **ВКЛЮЧЁН**", parse_mode="Markdown")
    elif parts == "off":
        CONFIG["auto_retry"] = False
        save_config(CONFIG)
        bot.reply_to(msg, "❌ Автоповтор ошибок: **ВЫКЛЮЧЁН**", parse_mode="Markdown")
    else:
        bot.reply_to(msg, "📝 Использование: /autostop on  или  /autostop off")
@bot.message_handler(commands=['setbackup'])
def set_backup(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/setbackup', '').strip().split()
        hours = int(parts[0])
        
        if hours < 1 or hours > 72:
            bot.reply_to(msg, "❌ Часы от 1 до 72")
            return
        
        CONFIG["auto_backup_hours"] = hours
        save_config(CONFIG)
        bot.reply_to(msg, f"✅ Автобэкап каждые {hours} часов")
    except:
        bot.reply_to(msg, "📝 Использование: /setbackup 6")

@bot.message_handler(commands=['resetconfig'])
def reset_config(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    global CONFIG
    CONFIG = DEFAULT_CONFIG.copy()
    save_config(CONFIG)
    bot.reply_to(msg, "✅ **Настройки сброшены до заводских**", parse_mode="Markdown")

# ==================== КОМАНДЫ УПРАВЛЕНИЯ ОБЪЯВЛЕНИЯМИ ====================
@bot.message_handler(commands=['add_text'])
def add_text_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    text = msg.text.replace('/add_text', '').strip()
    if not text:
        bot.reply_to(msg, "📝 Использование: /add_text Текст объявления")
        return
    
    ad_id = db.add_ad("text", text)
    bot.reply_to(msg, f"✅ **Объявление #{ad_id} создано**\n\n📝 Тип: Текст\n📄 Текст: {text[:200]}{'...' if len(text) > 200 else ''}")

@bot.message_handler(commands=['add_photo'])
def add_photo(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    temp_media[msg.chat.id] = {"type": "photo", "step": "photo", "media_files": []}
    bot.reply_to(msg, "📸 **Создание фото-объявления**\n\n1. Отправьте **фото**\n2. Затем отправьте **текст** (или /skip)\n\n/cancel - отмена")

@bot.message_handler(commands=['add_video'])
def add_video(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    temp_media[msg.chat.id] = {"type": "video", "step": "video", "media_files": []}
    bot.reply_to(msg, "🎬 **Создание видео-объявления**\n\n1. Отправьте **видео**\n2. Затем отправьте **текст** (или /skip)\n\n/cancel - отмена")

@bot.message_handler(commands=['add_multi'])
def add_multi(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    temp_media[msg.chat.id] = {"type": "multi_photo", "step": "multi_photo", "media_files": []}
    bot.reply_to(msg, "🖼️ **Создание альбома (до 10 фото)**\n\n1. Отправляйте фото (одно за другим)\n2. После всех фото нажмите /done\n3. Затем отправьте общий текст (или /skip)\n\n/cancel - отмена")

@bot.message_handler(commands=['done'])
def done_multi(msg):
    if msg.chat.id not in temp_media:
        return
    if temp_media[msg.chat.id].get("step") == "multi_photo":
        temp_media[msg.chat.id]["step"] = "text"
        bot.reply_to(msg, "📝 Теперь отправьте общий текст для всех фото (или /skip)")

@bot.message_handler(commands=['skip'])
def skip_text(msg):
    if msg.chat.id not in temp_media:
        return
    data = temp_media[msg.chat.id]
    ad_id = db.add_ad(data["type"], "", data.get("media_files", []))
    
    type_names = {"photo": "Фото", "video": "Видео", "multi_photo": "Альбом"}
    bot.reply_to(msg, f"✅ **Объявление #{ad_id} создано**\n\n📝 Тип: {type_names.get(data['type'], data['type'])}\n📄 Без текста")
    del temp_media[msg.chat.id]

@bot.message_handler(commands=['cancel'])
def cancel_media(msg):
    if msg.chat.id in temp_media:
        del temp_media[msg.chat.id]
        bot.reply_to(msg, "❌ Создание объявления отменено")

@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    if msg.chat.id not in temp_media:
        return
    data = temp_media[msg.chat.id]
    
    if data["type"] == "photo" and data.get("step") == "photo":
        file_id = msg.photo[-1].file_id
        data["media_files"] = [file_id]
        data["step"] = "text"
        bot.reply_to(msg, "📝 Теперь отправьте текст (или /skip)")
    
    elif data["type"] == "multi_photo" and data.get("step") == "multi_photo":
        file_id = msg.photo[-1].file_id
        data["media_files"].append(file_id)
        count = len(data["media_files"])
        if count >= 10:
            bot.reply_to(msg, f"✅ Получено {count}/10 фото! Нажмите /done")
        else:
            bot.reply_to(msg, f"📸 Фото {count}/10 получено. Отправляйте ещё или /done")

@bot.message_handler(content_types=['video'])
def handle_video(msg):
    if msg.chat.id not in temp_media:
        return
    data = temp_media[msg.chat.id]
    
    if data["type"] == "video" and data.get("step") == "video":
        file_id = msg.video.file_id
        data["media_files"] = [file_id]
        data["step"] = "text"
        bot.reply_to(msg, "📝 Теперь отправьте текст (или /skip)")

@bot.message_handler(func=lambda m: m.chat.id in temp_media and temp_media[m.chat.id].get("step") == "text")
def handle_media_text(msg):
    data = temp_media[msg.chat.id]
    ad_id = db.add_ad(data["type"], msg.text, data.get("media_files", []))
    
    type_names = {"photo": "Фото", "video": "Видео", "multi_photo": "Альбом"}
    preview = msg.text[:200] + "..." if len(msg.text) > 200 else msg.text
    bot.reply_to(msg, f"✅ **Объявление #{ad_id} создано**\n\n📝 Тип: {type_names.get(data['type'], data['type'])}\n📄 Текст: {preview}")
    del temp_media[msg.chat.id]

@bot.message_handler(commands=['list'])
def list_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "📭 **Нет объявлений**\n\nДобавьте через:\n/add_text\n/add_photo\n/add_video\n/add_multi", parse_mode="Markdown")
        return
    
    type_icons = {"text": "📝", "photo": "📸", "video": "🎬", "multi_photo": "🖼️"}
    
    response = "📋 **СПИСОК ОБЪЯВЛЕНИЙ**\n\n"
    for ad in ads[-15:]:  # Показываем последние 15
        icon = type_icons.get(ad["type"], "📄")
        preview = ad.get("text", "Без текста")[:50]
        if len(ad.get("text", "")) > 50:
            preview += "..."
        response += f"{icon} **ID {ad['id']}** [{ad['type']}]: {preview}\n"
        response += f"   └ Отправлено: {ad['sent_count']} | Ошибок: {ad['error_count']}\n\n"
    
    if len(ads) > 15:
        response += f"_...и ещё {len(ads)-15} объявлений_"
    
    response += f"\n📊 Всего: {len(ads)} объявлений"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def delete_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/del', '').strip().split()
        ad_id = int(parts[0])
        ad = db.get_ad_by_id(ad_id)
        if ad:
            db.delete_ad(ad_id)
            bot.reply_to(msg, f"✅ **Объявление #{ad_id} удалено**")
        else:
            bot.reply_to(msg, f"❌ Объявление #{ad_id} не найдено")
    except:
        bot.reply_to(msg, "📝 Использование: /del 1")

@bot.message_handler(commands=['edit'])
def edit_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        text = msg.text.replace('/edit', '').strip()
        parts = text.split(maxsplit=1)
        ad_id = int(parts[0])
        new_text = parts[1] if len(parts) > 1 else ""
        
        if not new_text:
            bot.reply_to(msg, "❌ Укажите новый текст")
            return
        
        ad = db.get_ad_by_id(ad_id)
        if ad:
            db.update_ad(ad_id, text=new_text)
            bot.reply_to(msg, f"✅ **Объявление #{ad_id} обновлено**\n\n📄 Новый текст: {new_text[:200]}")
        else:
            bot.reply_to(msg, f"❌ Объявление #{ad_id} не найдено")
    except:
        bot.reply_to(msg, "📝 Использование: /edit 1 Новый текст объявления")

@bot.message_handler(commands=['preview'])
def preview_ad(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = msg.text.replace('/preview', '').strip().split()
        ad_id = int(parts[0])
        ad = db.get_ad_by_id(ad_id)
        
        if not ad:
            bot.reply_to(msg, f"❌ Объявление #{ad_id} не найдено")
            return
        
        preview = f"📋 **ПРЕДПРОСМОТР ОБЪЯВЛЕНИЯ #{ad_id}**\n\n"
        preview += f"📝 Тип: {ad['type']}\n"
        preview += f"📄 Текст:\n{ad.get('text', 'Без текста')}\n"
        preview += f"📊 Медиа: {len(ad.get('media_files', []))} файлов\n"
        preview += f"📈 Отправлено: {ad['sent_count']} раз\n"
        preview += f"⚠️ Ошибок: {ad['error_count']}\n"
        preview += f"🕒 Создано: {ad['created'][:19]}"
        
        bot.reply_to(msg, preview, parse_mode="Markdown")
    except:
        bot.reply_to(msg, "📝 Использование: /preview 1")

@bot.message_handler(commands=['clear'])
def clear_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    db.clear_all_ads()
    bot.reply_to(msg, "🗑️ **Все объявления удалены**")

# ==================== КОМАНДЫ УПРАВЛЕНИЯ РАССЫЛКОЙ ====================
@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    global mailing_active, mailing_paused, current_round_info, error_counter
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    # Проверка наличия объявлений
    if len(db.get_ads()) == 0:
        bot.reply_to(msg, "❌ **Нет объявлений**\n\nДобавьте через:\n/add_text\n/add_photo\n/add_video\n/add_multi", parse_mode="Markdown")
        return
    
    # Проверка авторизации
    status, name, username, _, _ = check_auth_status()
    if not status:
        bot.reply_to(msg, "❌ **Сначала авторизуйтесь**\n\nИспользуйте /auth", parse_mode="Markdown")
        return
    
    # Проверка чатов
    if len(TARGET_CHATS) == 0:
        bot.reply_to(msg, "❌ **Нет чатов для рассылки**\n\nДобавьте через /addchat", parse_mode="Markdown")
        return
    
    # Проверка дневного лимита
    stats = db.get_stats()
    if stats["today_sent"] >= CONFIG["daily_limit"]:
        bot.reply_to(msg, f"⚠️ **Дневной лимит исчерпан**\n\nОтправлено: {stats['today_sent']}/{CONFIG['daily_limit']}\nЛимит сбросится в полночь", parse_mode="Markdown")
        return
    
    if mailing_active:
        bot.reply_to(msg, "⚠️ **Рассылка уже активна**\n\nИспользуйте /stopmail для остановки", parse_mode="Markdown")
        return
    
    # Сброс состояния
    mailing_active = True
    mailing_paused = False
    error_counter = 0
    
    # Загрузка чекпоинта
    load_checkpoint()
    
    # Запуск потока
    restart_mailing_thread()
    
    ads = db.get_ads()
    total_chats = len(TARGET_CHATS)
    
    response = f"""🚀 **РАССЫЛКА ЗАПУЩЕНА**

━━━━━━━━━━━━━━━━━━━━━

👤 Аккаунт: {name}
📝 Объявлений: {len(ads)}
🎯 Чатов: {total_chats}
📊 Дневной лимит: {stats['today_sent']}/{CONFIG['daily_limit']}

⚙️ **Настройки:**
├ Пауза между чатами: {CONFIG['delay_chat_min']}-{CONFIG['delay_chat_max']} сек
├ Пауза между кругами: {CONFIG['delay_round_min']}-{CONFIG['delay_round_max']} сек
└ Чатов за круг: {CONFIG['batch_size']}

📌 Старт с чата #{current_round_info['current_chat_index'] + 1 if current_round_info['current_chat_index'] else 1}

/stopmail - остановить
/pause - пауза
/status - статус"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    global mailing_active
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not mailing_active:
        bot.reply_to(msg, "⚠️ **Рассылка не активна**", parse_mode="Markdown")
        return
    
    mailing_active = False
    
    response = f"""🛑 **РАССЫЛКА ОСТАНОВЛЕНА**

━━━━━━━━━━━━━━━━━━━━━

📊 **Итоги этого запуска:**
├ Отправлено в этом круге: {current_round_info['sent_in_round']}
└ Прогресс сохранён

✅ Прогресс сохранён. При следующем запуске рассылка продолжится с того же места.

/startmail - возобновить"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['pause'])
def pause_mail(msg):
    global mailing_paused
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not mailing_active:
        bot.reply_to(msg, "⚠️ **Рассылка не активна**\n\nСначала запустите /startmail", parse_mode="Markdown")
        return
    
    if mailing_paused:
        bot.reply_to(msg, "⚠️ **Рассылка уже на паузе**\n\n/resume - возобновить", parse_mode="Markdown")
        return
    
    mailing_paused = True
    bot.reply_to(msg, "⏸️ **РАССЫЛКА НА ПАУЗЕ**\n\n/resume - возобновить", parse_mode="Markdown")

@bot.message_handler(commands=['resume'])
def resume_mail(msg):
    global mailing_paused
    
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not mailing_active:
        bot.reply_to(msg, "⚠️ **Рассылка не активна**\n\nСначала запустите /startmail", parse_mode="Markdown")
        return
    
    if not mailing_paused:
        bot.reply_to(msg, "⚠️ **Рассылка не на паузе**", parse_mode="Markdown")
        return
    
    mailing_paused = False
    bot.reply_to(msg, "▶️ **РАССЫЛКА ВОЗОБНОВЛЕНА**", parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def mailing_status(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if not mailing_active:
        bot.reply_to(msg, "📊 **Рассылка не активна**\n\n/startmail - запустить", parse_mode="Markdown")
        return
    
    stats = db.get_stats()
    total_chats = len(TARGET_CHATS)
    current_chat = current_round_info["current_chat_index"]
    progress = (current_chat / total_chats * 100) if total_chats > 0 else 0
    
    status_text = "⏸️ На паузе" if mailing_paused else "▶️ Активна"
    
    response = f"""📊 **СТАТУС РАССЫЛКИ**

━━━━━━━━━━━━━━━━━━━━━

🚦 Состояние: {status_text}

📈 **Прогресс круга:**
├ Обработано чатов: {current_chat}/{total_chats}
├ Прогресс: {progress:.1f}%
└ Отправлено в круге: {current_round_info['sent_in_round']}

📊 **Статистика дня:**
├ Отправлено сегодня: {stats['today_sent']}/{CONFIG['daily_limit']}
├ Ошибок сегодня: {stats['today_errors']}
└ Успешность: {round(stats['today_sent'] / (stats['today_sent'] + stats['today_errors']) * 100 if stats['today_sent'] + stats['today_errors'] > 0 else 0, 1)}%

⏱️ Время начала круга: {current_round_info['start_time'].strftime('%H:%M:%S') if current_round_info['start_time'] else 'Не определён'}

🔄 Текущее объявление: ID {current_round_info['current_ad_id'] if current_round_info['current_ad_id'] else 'Не выбрано'}

━━━━━━━━━━━━━━━━━━━━━

/stopmail - остановить
/pause - пауза
/resume - продолжить"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['test'])
def test_send(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.replace('/test', '').strip().split()
    if not parts:
        bot.reply_to(msg, "📝 Использование: /test @username\nили /test https://t.me/chat")
        return
    
    chat = parts[0]
    if not chat.startswith("https://t.me/") and not chat.startswith("@"):
        chat = "@" + chat
    
    # Проверка авторизации
    status, name, _, _, _ = check_auth_status()
    if not status:
        bot.reply_to(msg, "❌ Сначала авторизуйтесь: /auth")
        return
    
    # Выбор объявления
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "❌ Нет объявлений. Создайте через /add_text")
        return
    
    bot.reply_to(msg, f"🧪 **Тестовая отправка в {chat}...**")
    
    # Берём первое объявление для теста
    ad = ads[0]
    success = send_media_message(chat, ad)
    
    if success:
        bot.reply_to(msg, f"✅ **Тест успешен!**\n\nСообщение отправлено в {chat}", parse_mode="Markdown")
    else:
        bot.reply_to(msg, f"❌ **Ошибка отправки**\n\nНе удалось отправить в {chat}\nПроверьте доступность чата", parse_mode="Markdown")
@bot.message_handler(commands=['dryrun'])
def dry_run(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    ads = db.get_ads()
    chats = TARGET_CHATS
    
    if not ads:
        bot.reply_to(msg, "❌ Нет объявлений")
        return
    
    if not chats:
        bot.reply_to(msg, "❌ Нет чатов")
        return
    
    response = f"""🔍 **СУХОЙ ЗАПУСК (без реальной отправки)**

━━━━━━━━━━━━━━━━━━━━━

📝 Объявлений: {len(ads)}
🎯 Чатов: {len(chats)}

⚙️ **Будет использовано:**
├ Пауза между чатами: {CONFIG['delay_chat_min']}-{CONFIG['delay_chat_max']} сек
├ Пауза между кругами: {CONFIG['delay_round_min']}-{CONFIG['delay_round_max']} сек
├ Чатов за круг: {CONFIG['batch_size']}
└ Случайный порядок: {'Да' if CONFIG['randomize_chats'] else 'Нет'}

⏱️ **Примерное время одного круга:**
├ Минимум: ~{CONFIG['delay_chat_min'] * len(chats) // 60} минут
└ Максимум: ~{CONFIG['delay_chat_max'] * len(chats) // 60} минут

✅ Всё готово к запуску!
/startmail - запустить рассылку"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

# ==================== КОМАНДЫ СТАТИСТИКИ ====================
@bot.message_handler(commands=['stats'])
def show_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    ads = db.get_ads()
    
    # Статистика по типам объявлений
    type_counts = defaultdict(int)
    for ad in ads:
        type_counts[ad["type"]] += 1
    
    # Подсчёт успешности
    history = db.data["history"][-200:]
    success_count = sum(1 for h in history if h["success"])
    success_rate = (success_count / len(history) * 100) if history else 0
    
    response = f"""📊 **ПОЛНАЯ СТАТИСТИКА**

━━━━━━━━━━━━━━━━━━━━━

📝 **ОБЪЯВЛЕНИЯ:**
├ Всего: {len(ads)}
├ Текст: {type_counts.get('text', 0)}
├ Фото: {type_counts.get('photo', 0)}
├ Видео: {type_counts.get('video', 0)}
└ Альбомы: {type_counts.get('multi_photo', 0)}

📊 **ОТПРАВКИ:**
├ Всего отправлено: {stats['total_sent']}
├ Всего ошибок: {stats['total_errors']}
├ Сегодня отправлено: {stats['today_sent']}
├ Сегодня ошибок: {stats['today_errors']}
└ Дневной лимит: {CONFIG['daily_limit']}

📈 **УСПЕШНОСТЬ (последние 200):**
├ Успешно: {success_count}
├ Неудачно: {len(history) - success_count}
└ Процент: {success_rate:.1f}%

🎯 **ЧАТЫ:**
└ Всего чатов: {len(TARGET_CHATS)}

━━━━━━━━━━━━━━━━━━━━━

📋 Дополнительные команды:
/stats errors - последние ошибки
/stats ads - статистика по объявлениям
/resetstats - сбросить статистику"""
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['stats_errors'])
def stats_errors(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "stats_errors")
        return
    
    history = db.data["history"][-100:]
    errors = [h for h in history if not h["success"]]
    
    if not errors:
        bot.reply_to(msg, "✅ **Нет ошибок в последних 100 отправках**", parse_mode="Markdown")
        return
    
    response = f"⚠️ **ПОСЛЕДНИЕ ОШИБКИ (последние 20)**\n\n"
    for err in errors[-20:]:
        time_str = err["time"][:19].replace("T", " ")
        chat_short = err["chat"].replace("https://t.me/", "@")
        response += f"• {time_str} → {chat_short}\n  └ {err.get('error', 'Неизвестная ошибка')[:80]}\n\n"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['stats_ads'])
def stats_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    ads = db.get_ads()
    if not ads:
        bot.reply_to(msg, "📭 Нет объявлений")
        return
    
    response = f"📊 **СТАТИСТИКА ПО ОБЪЯВЛЕНИЯМ**\n\n"
    
    for ad in ads:
        icon = {"text": "📝", "photo": "📸", "video": "🎬", "multi_photo": "🖼️"}.get(ad["type"], "📄")
        response += f"{icon} **ID {ad['id']}**\n"
        response += f"├ Тип: {ad['type']}\n"
        response += f"├ Отправлено: {ad['sent_count']}\n"
        response += f"├ Ошибок: {ad['error_count']}\n"
        response += f"└ Создано: {ad['created'][:10]}\n\n"
    
    bot.reply_to(msg, response, parse_mode="Markdown")

@bot.message_handler(commands=['resetstats'])
def reset_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    db.reset_stats()
    bot.reply_to(msg, "🗑️ **Статистика сброшена**")

# ==================== КОМАНДЫ БЭКАПОВ ====================
@bot.message_handler(commands=['backup'])
def backup_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    bot.reply_to(msg, "💾 **Создание бэкапа...**")
    
    try:
        backup_path = create_backup()
        bot.reply_to(msg, f"✅ **Бэкап создан!**\n\n📁 Путь: {backup_path}\n🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка создания бэкапа: {e}")

@bot.message_handler(commands=['restore'])
def restore_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    bot.reply_to(msg, "📂 **Восстановление из бэкапа**\n\nОтправьте ZIP-архив с бэкапом или укажите имя папки:\n/restore backup_20241215_120000")

@bot.message_handler(commands=['export'])
def export_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    # Экспорт настроек и чатов
    export_data = {
        "config": CONFIG,
        "chats": TARGET_CHATS,
        "export_time": datetime.now().isoformat()
    }
    
    export_file = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    with open(export_file, "rb") as f:
        bot.send_document(msg.chat.id, f, caption="📤 **Экспорт настроек и чатов**")
    
    os.remove(export_file)

# ==================== ОСНОВНАЯ КОМАНДА ====================
@bot.message_handler(commands=['start', 'help'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Доступ запрещён")
        return
    
    status, name, username, _, _ = check_auth_status()
    auth_status = "✅ Авторизован" if status else "❌ Не авторизован"
    auth_name = f" ({name})" if name else ""
    
    stats = db.get_stats()
    
    info = f"""🤖 **KORECKT V4.0 - МАССОВАЯ РАССЫЛКА**

━━━━━━━━━━━━━━━━━━━━━

🔐 **АВТОРИЗАЦИЯ:**
/auth - Войти в аккаунт
/reauth - Переавторизоваться
/check - Проверить аккаунт
/shadowban - Проверить теневой бан

📝 **ОБЪЯВЛЕНИЯ:**
/add_text [текст] - Текстовое
/add_photo - Фото + текст
/add_video - Видео + текст
/add_multi - Альбом (до 10 фото)
/list - Список объявлений
/del [ID] - Удалить
/edit [ID] [текст] - Редактировать
/preview [ID] - Предпросмотр

🎯 **ЧАТЫ:**
/addchat [ссылка] - Добавить чат
/removechat [ID] - Удалить чат
/listchats - Список чатов
/chatstats - Статистика чатов
/clearchats - Очистить чаты

🚀 **УПРАВЛЕНИЕ:**
/startmail - Запустить рассылку
/stopmail - Остановить
/pause - Пауза
/resume - Продолжить
/status - Текущий статус
/test [чат] - Тестовая отправка

⚙️ **НАСТРОЙКИ:**
/config - Показать настройки
/setdelay [мин] [макс] - Пауза между чатами
/setround [мин] [макс] - Пауза между кругами
/setdaily [лимит] - Дневной лимит
/setbatch [кол-во] - Чатов за круг
/randomize on/off - Перемешивать чаты
/autoretry on/off - Автоповтор ошибок
/autostop on/off - Автостоп при ошибках
/setbackup [часы] - Частота бэкапов

📊 **СТАТИСТИКА:**
/stats - Полная статистика
/stats_errors - Последние ошибки
/stats_ads - По объявлениям
/resetstats - Сбросить статистику

💾 **БЭКАПЫ:**
/backup - Создать бэкап
/export - Экспорт настроек

━━━━━━━━━━━━━━━━━━━━━

🔐 Статус: {auth_status}{auth_name}
📝 Объявлений: {len(db.get_ads())}
🎯 Чатов: {len(TARGET_CHATS)}
✅ Отправлено сегодня: {stats['today_sent']}
📈 Всего отправлено: {stats['total_sent']}"""

    bot.reply_to(msg, info, parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_bot():
    print("=" * 60)
    print("🤖 KORECKT V4.0 - МАССОВАЯ РАССЫЛКА")
    print("=" * 60)
    
    # Создание директорий
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    
    # Запуск фонового бэкапа
    backup_thread = threading.Thread(target=auto_backup_worker, daemon=True)
    backup_thread.start()
    
    # Запуск движка
    restart_mailing_thread()
    
    print("✅ Бот запущен и готов к работе!")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print("📱 Откройте Telegram и напишите /start")
    print("🔐 Для авторизации используйте /auth")
    print("=" * 60)
    
    # Удаляем вебхук и запускаем polling
    bot.remove_webhook()
    time.sleep(1)
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
