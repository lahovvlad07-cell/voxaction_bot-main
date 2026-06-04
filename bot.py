import asyncio
import os
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

# ---------- Flask (для Keep-Alive на Render) ----------
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
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-frontend.vercel.app")  # замените на ваш Vercel адрес

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None
    if ref_code and ref_code.startswith('REF'):
        referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
        if referrer.data and referrer.data[0]['id'] != message.from_user.id:
            supabase.table('users').update({'referred_by': referrer.data[0]['id']}).eq('id', message.from_user.id).execute()
            supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 500')}).eq('id', referrer.data[0]['id']).execute()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций!", reply_markup=kb)

@dp.message(Command("topup_10"))
async def topup_10(message: types.Message):
    prices = [LabeledPrice(label="Пополнение Stars", amount=1000)]  # 10 Stars (1000 копеек)
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Пополнение баланса",
        description="Пополните баланс на 10 Telegram Stars для торговли акциями.",
        payload="topup_10",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="topup_10"
    )

@dp.message(Command("withdraw"))
async def withdraw(message: types.Message):
    await message.answer("Вывод через подарки временно недоступен. Свяжитесь с администратором @ваш_админ")

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
