import asyncio
import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)

# ---------- Environment variables validation ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-bot.vercel.app")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Адрес вашего бота на Render + '/webhook'

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_URL and SUPABASE_KEY must be set")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN must be set")
if not WEBHOOK_URL:
    raise ValueError("❌ WEBHOOK_URL must be set (e.g. https://voxaction-bot-main.onrender.com/webhook)")

logging.info("✅ Environment variables loaded")

# ---------- Supabase client ----------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Telegram Bot ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Flask app for invoice creation and webhook ----------
app_flask = Flask(__name__)
CORS(app_flask)  # разрешаем запросы с Vercel

@app_flask.route('/')
def health():
    """Health check endpoint for Render."""
    return "Bot is running", 200

@app_flask.route('/webhook', methods=['POST'])
async def telegram_webhook():
    """Endpoint для получения обновлений от Telegram (webhook)."""
    update = types.Update.model_validate(await request.get_json())
    await dp.feed_update(bot, update)
    return "OK", 200

@app_flask.route('/create-invoice', methods=['POST'])
async def create_invoice():
    """Создаёт инвойс и возвращает ссылку."""
    data = request.get_json()
    telegram_id = data.get('user_id')
    amount = data.get('amount')

    if not telegram_id or not amount:
        return jsonify({"ok": False, "error": "Missing user_id or amount"}), 400

    try:
        amount = int(amount)
    except ValueError:
        return jsonify({"ok": False, "error": "Amount must be a number"}), 400

    if amount < 1 or amount > 10000:
        return jsonify({"ok": False, "error": "Amount must be 1–10000"}), 400

    try:
        # Создаём инвойс (это уже асинхронный метод, вызываем напрямую)
        invoice_link = await bot.create_invoice_link(
            title="Пополнение баланса",
            description=f"Пополнение на {amount} ⭐",
            payload=f"topup_{amount}_{telegram_id}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{amount} Stars", "amount": amount * 100}]
        )
        return jsonify({"ok": True, "invoice_link": invoice_link})
    except Exception as e:
        logging.error(f"Error creating invoice: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ---------- Telegram Bot Handlers ----------
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('REF'):
        ref_code = args[1]
        referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
        if referrer.data and referrer.data[0]['id'] != message.from_user.id:
            supabase.table('users').update({'referred_by': referrer.data[0]['id']}).eq('id', message.from_user.id).execute()
            supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 500')}).eq('id', referrer.data[0]['id']).execute()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций!", reply_markup=kb)

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment(message: types.Message):
    amount_stars = message.successful_payment.total_amount // 100
    user_id = message.from_user.id
    supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + ?', amount_stars)}).eq('id', user_id).execute()
    await message.answer(f"✅ Баланс пополнен на {amount_stars} ⭐")

# ---------- Webhook setup and cleanup ----------
async def set_webhook():
    """Устанавливает вебхук при старте."""
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

async def on_startup():
    """Выполняется перед запуском веб-сервера."""
    await set_webhook()
    # Создаём задачу для бота, но она не нужна, так как обновления будут приходить через /webhook

# ---------- Main entry point ----------
async def main():
    # Инициализация вебхука
    await on_startup()
    # Запускаем Flask-сервер (без запуска polling бота)
    import uvicorn
    config = uvicorn.Config(app_flask, host="0.0.0.0", port=int(os.environ.get('PORT', 8000)), loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
