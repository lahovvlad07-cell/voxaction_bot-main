import asyncio
import os
import json
from threading import Thread
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client, Client

# ---------- Конфигурация ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-frontend.onrender.com")  # адрес вашего Mini App
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://gsutnhhklidxmewdkcvk.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdzdXRuaGhrbGlkeG1ld2RrY3ZrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1NzA2MTEsImV4cCI6MjA5NjE0NjYxMX0.XEtyJVT0BfmEgAAsGagPHRdHhmCgrtWEbtzov0c3EXc")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Flask сервер для уведомлений (опционально) ----------
flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    # Сюда можно принимать уведомления от Supabase или от вашего фронтенда
    data = request.json
    # Пример: {"user_id": 123, "message": "Ваша сделка выполнена"}
    user_id = data.get('user_id')
    text = data.get('message')
    if user_id and text:
        asyncio.run_coroutine_threadsafe(bot.send_message(user_id, text), asyncio.get_event_loop())
    return jsonify({"ok": True})

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=False)

# ---------- Команды бота ----------
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций! Используйте кнопку ниже, чтобы начать торговлю.", reply_markup=kb)

@dp.message(Command("topup"))
async def topup_cmd(message: types.Message):
    # Создаём инвойс на 10 Stars (1000 копеек). Можно сделать выбор суммы.
    prices = [LabeledPrice(label="Пополнение баланса", amount=1000)]  # 1000 копеек = 10 Stars
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Пополнение Stars",
        description="Пополните баланс Stars для участия в торгах.",
        payload="topup",
        provider_token="",  # Для Telegram Stars оставляем пустым
        currency="XTR",
        prices=prices,
        start_parameter="topup"
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Всегда подтверждаем
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment())
async def process_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    amount_stars = message.successful_payment.total_amount // 100  # переводим из копеек в Stars
    user_id = message.from_user.id
    # Обновляем баланс пользователя в Supabase
    try:
        # Получаем текущий баланс
        user_data = supabase.table('users').select('stars_balance').eq('id', user_id).execute()
        if user_data.data:
            current_balance = user_data.data[0]['stars_balance']
            new_balance = current_balance + amount_stars * 100  # добавляем в копейках
            supabase.table('users').update({'stars_balance': new_balance}).eq('id', user_id).execute()
        else:
            # Создаём пользователя, если его нет (на всякий случай)
            supabase.table('users').insert({'id': user_id, 'username': message.from_user.username or "user", 'shares': 0, 'stars_balance': amount_stars * 100}).execute()
        await message.answer(f"✅ Баланс успешно пополнен на {amount_stars} ⭐")
    except Exception as e:
        await message.answer(f"❌ Ошибка пополнения: {e}")
        print(e)

# ---------- Функция для отправки уведомлений (вызывается из триггера или из кода) ----------
async def send_notification(user_id: int, text: str):
    # Проверяем настройки уведомлений пользователя
    try:
        user = supabase.table('users').select('notifications_enabled').eq('id', user_id).execute()
        if user.data and user.data[0].get('notifications_enabled', True):
            await bot.send_message(user_id, text)
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

# ---------- Запуск бота и Flask ----------
async def main():
    # Запускаем Flask в отдельном потоке (для вебхуков, если нужно)
    Thread(target=run_flask, daemon=True).start()
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
