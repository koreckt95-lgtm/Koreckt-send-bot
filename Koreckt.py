import telebot
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
import threading
import time
import random
import json
import os

# ==================== НАСТРОЙКИ ====================
API_ID = 34701116
API_HASH = 'd481bf8b670a865da717155f6af892c2'
BOT_TOKEN = '8600586993:AAGyDp9AXOj5Qvl7Q52D68gDiuUbxLDwKLA'
ADMIN_ID = 2097475960

# Файлы
CHATS_FILE = "chats.json"
ADS_FILE = "ads.json"
SESSION_FILE = "kor_session.session"

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

# ==================== ГЛОБАЛЬНЫЕ ====================
bot = telebot.TeleBot(BOT_TOKEN)
client = None
mailing_active = False
delay_min = 150
delay_max = 400
stats = {"sent": 0, "errors": 0}

# ==================== ПОДКЛЮЧЕНИЕ СЕССИИ ====================
def init_client():
    global client
    if not os.path.exists(SESSION_FILE):
        print(f"❌ Файл {SESSION_FILE} не найден!")
        return False
    try:
        client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
        client.connect()
        if client.is_user_authorized():
            me = client.get_me()
            print(f"✅ Авторизован: {me.first_name}")
            return True
        else:
            print("❌ Сессия не валидна")
            return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

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
        time.sleep(e.seconds)
        return False
    except Exception as e:
        print(e)
        return False

def mailing_loop():
    global mailing_active, stats
    while True:
        if not mailing_active or not client:
            time.sleep(2)
            continue
        
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
                print(f"✅ {chat}")
            else:
                stats["errors"] += 1
                print(f"❌ {chat}")
                time.sleep(60)
            
            time.sleep(random.uniform(delay_min, delay_max))
        
        print("Круг завершён, пауза 5-10 минут...")
        time.sleep(random.uniform(300, 600))

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    info = f"""🤖 KORECKT БОТ

📁 Сессия: {'✅' if client else '❌'}
📝 Объявлений: {len(load_ads())}
🎯 Чатов: {len(load_chats())}
📨 Отправлено: {stats['sent']}
🚀 Рассылка: {'✅' if mailing_active else '❌'}

━━━━━━━━━━━━━━━━━

/add [текст] - текст
/add_photo - фото+текст
/list - список
/del [ID] - удалить

/addchat [ссылка] - добавить чат
/removechat [номер] - удалить
/listchats - список

/startmail - запуск
/stopmail - остановка
/setdelay 150 400 - пауза
/stats - статистика
/check - проверка"""
    bot.reply_to(msg, info)

@bot.message_handler(commands=['add'])
def add_text(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    text = msg.text.replace('/add', '').strip()
    if not text:
        bot.reply_to(msg, "❌ /add Текст")
        return
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "text", "text": text})
    save_ads(ads)
    bot.reply_to(msg, f"✅ Объявление #{ad_id}")

@bot.message_handler(commands=['add_photo'])
def add_photo(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    bot.reply_to(msg, "📸 Отправьте ФОТО")
    bot.register_next_step_handler(msg, save_photo)

def save_photo(msg):
    if not msg.photo:
        bot.reply_to(msg, "❌ Отправьте фото")
        return
    photo = msg.photo[-1].file_id
    bot.reply_to(msg, "📝 Отправьте ТЕКСТ (или /skip)")
    bot.register_next_step_handler(msg, lambda m: save_photo_text(m, photo))

def save_photo_text(msg, photo):
    text = msg.text if msg.text != "/skip" else ""
    ads = load_ads()
    ad_id = len(ads) + 1
    ads.append({"id": ad_id, "type": "photo", "text": text, "photo": photo})
    save_ads(ads)
    bot.reply_to(msg, f"✅ Объявление #{ad_id} (фото+текст)")

@bot.message_handler(commands=['list'])
def list_ads(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    ads = load_ads()
    if not ads:
        bot.reply_to(msg, "Нет объявлений")
        return
    response = "📝 Объявления:\n\n"
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
        bot.reply_to(msg, "Уже есть")

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
        bot.reply_to(msg, "Нет чатов")
        return
    response = "🎯 Чаты:\n\n"
    for i, chat in enumerate(chats[:30], 1):
        short = chat.replace("https://t.me/", "@")
        response += f"{i}. {short}\n"
    bot.reply_to(msg, response)

@bot.message_handler(commands=['startmail'])
def start_mail(msg):
    global mailing_active
    if msg.from_user.id != ADMIN_ID:
        return
    if not client:
        bot.reply_to(msg, "❌ Нет сессии! Добавь Secret File: kor_session.session")
        return
    if len(load_ads()) == 0:
        bot.reply_to(msg, "❌ Нет объявлений")
        return
    if len(load_chats()) == 0:
        bot.reply_to(msg, "❌ Нет чатов")
        return
    mailing_active = True
    bot.reply_to(msg, "🚀 РАССЫЛКА ЗАПУЩЕНА")
    threading.Thread(target=mailing_loop, daemon=True).start()

@bot.message_handler(commands=['stopmail'])
def stop_mail(msg):
    global mailing_active
    if msg.from_user.id != ADMIN_ID:
        return
    mailing_active = False
    bot.reply_to(msg, "🛑 ОСТАНОВЛЕНО")

@bot.message_handler(commands=['setdelay'])
def set_delay(msg):
    global delay_min, delay_max
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.replace('/setdelay', '').strip().split()
        delay_min = int(parts[0])
        delay_max = int(parts[1])
        bot.reply_to(msg, f"✅ {delay_min}-{delay_max} сек")
    except:
        bot.reply_to(msg, "❌ /setdelay 150 400")

@bot.message_handler(commands=['stats'])
def show_stats(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    bot.reply_to(msg, f"📊 Отправлено: {stats['sent']}\n❌ Ошибок: {stats['errors']}\n🎯 Чатов: {len(load_chats())}\n📝 Объявлений: {len(load_ads())}")

@bot.message_handler(commands=['check'])
def check(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    if not client:
        bot.reply_to(msg, "❌ Нет сессии")
        return
    try:
        me = client.get_me()
        bot.reply_to(msg, f"✅ {me.first_name}\n🆔 {me.id}\nСтатус: OK")
    except:
        bot.reply_to(msg, "❌ Ошибка")

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
    print("KORECKT BOT")
    print("=" * 50)
    
    init_client()
    
    threading.Thread(target=start_flask, daemon=True).start()
    
    print("Бот запущен!")
    
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
