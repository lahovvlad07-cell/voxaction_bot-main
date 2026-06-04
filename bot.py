import asyncio
import os
import logging
from threading import Thread
from flask import Flask, request, jsonify
from flask_cors import CORS
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

logging.basicConfig(level=logging.INFO)

# ---------- Проверка переменных окружения ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-bot.vercel.app")  # замените при необходимости

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_URL and SUPABASE_KEY must be set")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN must be set")

# ---------- Flask ----------
app_flask = Flask(__name__)
CORS(app_flask)

@app_flask.route('/')
def health():
    return "Bot is running", 200

@app_flask.route('/create-invoice', methods=['POST'])
def create_invoice():
    data = request.get_json()
    telegram_id = data.get('user_id')
    amount = data.get('amount')
    if not telegram_id or not amount:
        return jsonify({"ok": False, "error": "Missing user_id or amount"}), 400
    try:
        amount = int(amount)
    except:
        return jsonify({"ok": False, "error": "Amount must be integer"}), 400
    if amount < 1 or amount > 10000:
        return jsonify({"ok": False, "error": "Amount must be 1-10000"}), 400

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        invoice_link = loop.run_until_complete(
            bot.create_invoice_link(
                title="Пополнение баланса",
                description=f"Пополнение на {amount} ⭐",
                payload=f"topup_{amount}_{telegram_id}",
                provider_token="",
                currency="XTR",
                prices=[{"label": f"{amount} Stars", "amount": amount * 100}]
            )
        )
        loop.close()
        return jsonify({"ok": True, "invoice_link": invoice_link})
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

# ---------- Supabase ----------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Telegram Bot ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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

async def main():
    # Запускаем Flask в фоновом потоке
    Thread(target=run_flask, daemon=True).start()
    # Удаляем вебхук на всякий случай
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
