import asyncio
import os
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

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
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-frontend.vercel.app")  # замените

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Обработчик команды /start (включая реферальную ссылку и пополнение)
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    if len(args) > 1:
        param = args[1]
        # Обработка пополнения: start=topup_XXX
        if param.startswith('topup_'):
            amount_str = param.replace('topup_', '')
            try:
                amount = int(amount_str)
                await send_invoice(message, amount)
                return
            except:
                pass
        # Обработка реферального кода
        elif param.startswith('REF'):
            ref_code = param
            referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
            if referrer.data and referrer.data[0]['id'] != message.from_user.id:
                supabase.table('users').update({'referred_by': referrer.data[0]['id']}).eq('id', message.from_user.id).execute()
                supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 500')}).eq('id', referrer.data[0]['id']).execute()
        elif param == 'withdraw_gifts':
            await message.answer("Вывод через подарки в разработке. Скоро появится!")
            return
        elif param == 'withdraw_ton':
            await message.answer("Вывод в TON в разработке. Скоро появится!")
            return
    # Обычный старт
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций!", reply_markup=kb)

async def send_invoice(message: types.Message, stars_amount: int):
    if stars_amount < 1 or stars_amount > 10000:
        await message.answer("Сумма должна быть от 1 до 10000 Stars")
        return
    amount_cents = stars_amount * 100  # Telegram ожидает копейки
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

# Заглушки для вывода (можно убрать, они не нужны)
# @dp.message(Command("withdraw_gifts"))
# async def withdraw_gifts(message: types.Message):
#     await message.answer("Вывод через подарки в разработке.")

# @dp.message(Command("withdraw_ton"))
# async def withdraw_ton(message: types.Message):
#     await message.answer("Вывод в TON в разработке.")

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment(message: types.Message):
    amount_stars = message.successful_payment.total_amount // 100  # копейки -> звёзды
    user_id = message.from_user.id
    supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + ?', amount_stars)}).eq('id', user_id).execute()
    await message.answer(f"✅ Баланс пополнен на {amount_stars} ⭐")

async def main():
    Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
