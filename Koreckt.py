import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
import threading
import time
import random
import json
import os
from datetime import datetime

# ==================== ПЕРЕМЕННЫЕ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")

# Файлы
CHATS_FILE = "chats.json"
ADS_FILE = "ads.json"
SESSION_FILE = "kor_session.session"  # Загруженный файл сессии

# ==================== ЗАГРУЗКА ДАННЫХ ====================
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

# Настройки
config = {
    "delay_min": 150,
    "delay_max": 400,
    "daily_limit": 100,
    "active": False
}

stats = {"sent": 0, "errors": 0, "today": 0, "last_date": datetime.now().date().isoformat()}

# ==================== БОТ ====================
bot = telebot.TeleBot(BOT_TOKEN)
client = None
temp_media = {}

def init_client():
    """Инициализация клиента с готовой сессией"""
    global client
    try:
        if os.path.exists(SESSION_FILE):
            print(f"✅ Найден файл сессии: {SESSION_FILE}")
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
            client.connect()
            
            if client.is_user_authorized():
                me = client.get_me()
                print(f"✅ Авторизован: {me.first_name} (@{me.username})")
                return True
            else:
                print("❌ Сессия не активна, нужна переавторизация")
                return False
        else:
            print("❌ Файл сессии не найден!")
            return False
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        return False

# ==================== ОТПРАВКА ====================
def send_message(chat, text, photo=None):
    global client
    try:
        if photo:
            client.send_file(chat, photo, caption=text)
        else:
            time.sleep(random.uniform(2, 6))
            client.send_message(chat, text)
        return True
    except FloodWaitError as e:
        print(f"Flood: {e.seconds} сек")
        time.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"Ошибка: {e}")
        return False

def mailing_loop():
    global stats
    while True:
        if not config["active"] or not client:
            time.sleep(2)
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
            continue
        
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
            
            time.sleep(random.uniform(config["delay_min"], config["delay_max"]))
        
        print("Круг завершён, пауза...")
        time.sleep(random.uniform(300, 600))

# ==================== КОМАНДЫ БОТА ====================
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    is_auth = client and client.is_connected() if client else False
    auth_status = "✅" if is_auth else "❌"
    
    text = f"""
🤖 **KORECKT БОТ**

🔐 Статус: {auth_status}
📝 Объявлений: {len(load_ads())}
🎯 Чатов: {len(load_chats())}
📊 Сегодня: {stats['today']}/{config['daily_limit']}
🚀 Рассылка: {'✅' if config['active'] else '❌'}

━━━━━━━━━━━━━━━━━

📝 **ОБЪЯВЛЕНИЯ:**
/add_text Текст - текст
/add_photo - фото+текст
/list - список
/del [ID] - удалить

🎯 **ЧАТЫ:**
/addchat [ссылка] - добавить
/removechat [ID] - удалить
/listchats - список

🚀 **УПРАВЛЕНИЕ:**
/startmail - запуск
/stopmail - остановка
/setdelay 150 400 - пауза
/setdaily 100 - лимит

📊 **СТАТИСТИКА:**
/stats - показать
"""
    bot.reply_to(msg, text, parse_mode="Markdown")

@bot.message_handler(commands=['add_text'])
def add_text(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add_text', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add_text Текст")
        return
    
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "text", "text": text, "photo": None})
    save_ads(ads)
    bot.reply_to(msg, f"✅ Объявление #{ad_id}")

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
        bot.reply_to(msg, f"✅ Объявление #{ad_id}")
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
    bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото+текст)")

@bot.message_handler(commands=['list'])
def list_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    ads = load_ads()
    if not ads:
        bot.reply_to(msg, "📭 Нет")
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
        bot.reply_to(msg, f"✅ #{ad_id} удалено")
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
        bot.reply_to(msg, f"✅ {chat}")
    else:
        bot.reply_to(msg, "⚠️ Уже есть")

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
            bot.reply_to(msg, f"✅ {removed}")
        else:
            bot.reply_to(msg, "❌ Неверный номер")
    else:
        chat = parts[0]
        if chat in chats:
            chats.remove(chat)
            save_chats(chats)
            bot.reply_to(msg, f"✅ {chat}")

@bot.message_handler(commands=['listchats'])
def list_chats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    chats = load_chats()
    if not chats:
        bot.reply_to(msg, "📭 Нет")
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
    if not client:
        bot.reply_to(msg, "❌ Нет сессии. Загрузите файл kor_session.session")
        return
    if len(load_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений")
        return
    if len(load_chats()) == 0:
        bot.reply_to(msg, "❌ Нет чатов")
        return
    
    config["active"] = True
    bot.reply_to(msg, "🚀 **Рассылка запущена!**")

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    config["active"] = False
    bot.reply_to(msg, "🛑 **Остановлено**")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        config["delay_min"] = int(parts[0])
        config["delay_max"] = int(parts[1])
        bot.reply_to(msg, f"✅ {config['delay_min']}-{config['delay_max']} сек")
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

📨 Отправлено: {stats['sent']}
❌ Ошибок: {stats['errors']}
📈 Успешность: {success_rate:.1f}%

📅 Сегодня: {stats['today']}/{config['daily_limit']}
🎯 Чатов: {len(load_chats())}
📝 Объявлений: {len(load_ads())}

🚀 Рассылка: {'✅' if config['active'] else '❌'}
"""
    bot.reply_to(msg, text, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def check_account(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not client:
        bot.reply_to(msg, "❌ Нет сессии")
        return
    
    try:
        me = client.get_me()
        text = f"""
✅ **Аккаунт**

👤 {me.first_name}
🆔 {me.id}
📱 Premium: {'Да' if me.premium else 'Нет'}

⚠️ Бан: Нет
"""
        bot.reply_to(msg, text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(msg, f"❌ {e}")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("🤖 KORECKT БОТ")
    print("=" * 40)
    
    # Загружаем сессию
    if init_client():
        print("✅ Готов к работе!")
    else:
        print("⚠️ Сессия не загружена, рассылка не будет работать")
    
    # Запуск рассылки
    thread = threading.Thread(target=mailing_loop, daemon=True)
    thread.start()
    
    # Flask для Render
    try:
        from flask import Flask
        app = Flask(__name__)
        
        @app.route('/')
        def home():
            return "KORECKT Bot is running!"
        
        port = int(os.environ.get("PORT", 8080))
        threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()
        print(f"🌐 Flask на порту {port}")
    except:
        print("⚠️ Flask не установлен")
    
    print("=" * 40)
    print("Бот запущен!")
    
    # Запуск бота
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
