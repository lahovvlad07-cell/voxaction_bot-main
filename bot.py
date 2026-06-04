import asyncio
import os
import logging
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

logging.basicConfig(level=logging.INFO)

# ---------- Flask (Keep-Alive) ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot is running", 200

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

# ---------- Supabase ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Telegram Bot ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-frontend.vercel.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    logging.info(f"Start command args: {args}")
    if len(args) > 1:
        param = args[1]
        if param.startswith('topup_'):
            amount_str = param.replace('topup_', '')
            try:
                amount = int(amount_str)
                if 1 <= amount <= 10000:
                    await send_invoice(message, amount)
                    return
                else:
                    await message.answer("Сумма должна быть от 1 до 10000 Stars.")
                    return
            except:
                await message.answer("Неверная сумма.")
                return
        elif param.startswith('REF'):
            ref_code = param
            referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
            if referrer.data and referrer.data[0]['id'] != message.from_user.id:
                supabase.table('users').update({'referred_by': referrer.data[0]['id']}).eq('id', message.from_user.id).execute()
                supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 500')}).eq('id', referrer.data[0]['id']).execute()
    # Обычный старт
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций!", reply_markup=kb)

async def send_invoice(message: types.Message, stars_amount: int):
    amount_cents = stars_amount * 100
    prices = [LabeledPrice(label=f"{stars_amount} Stars", amount=amount_cents)]
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"Пополнение баланса на {stars_amount} ⭐",
        description=f"Вы получите {stars_amount} Telegram Stars на счёт в игре.",
        payload=f"topup_{stars_amount}",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter=f"topup_{stars_amount}"
    )

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
    Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
