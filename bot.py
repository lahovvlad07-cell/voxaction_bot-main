import asyncio
import os
import uuid
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from aiogram.client.default import DefaultBotProperties
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-frontend.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        try:
            referrer_id = int(message.text.split()[1])
        except:
            pass
    # Проверяем, существует ли пользователь
    res = supabase.table('users').select('id').eq('id', user_id).execute()
    if not res.data:
        supabase.table('users').insert({
            'id': user_id,
            'username': username,
            'shares': 0,
            'stars_balance': 0,
            'referrer_id': referrer_id,
            'referral_code': str(uuid.uuid4())[:8]
        }).execute()
    # Генерируем реферальную ссылку
    ref_code = supabase.table('users').select('referral_code').eq('id', user_id).execute().data[0]['referral_code']
    ref_link = f"https://t.me/{bot.username}?start={ref_code}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="ref_link")]
    ])
    await message.answer(
        f"Добро пожаловать, {username}!\n\nТоргуйте акциями, зарабатывайте Stars и приглашайте друзей.\n\nВаша реферальная ссылка: <code>{ref_link}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "ref_link")
async def send_ref_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_code = supabase.table('users').select('referral_code').eq('id', user_id).execute().data[0]['referral_code']
    ref_link = f"https://t.me/{bot.username}?start={ref_code}"
    await callback.message.answer(f"Ваша реферальная ссылка:\n<code>{ref_link}</code>", parse_mode="HTML")
    await callback.answer()

# Команда /topup (вызывается из Mini App через отправку сообщения)
@dp.message(Command("topup"))
async def topup_cmd(message: types.Message):
    args = message.text.split()
    amount = 10
    if len(args) > 1:
        try:
            amount = int(args[1])
            if amount < 1 or amount > 1000:
                amount = 10
        except:
            amount = 10
    prices = [LabeledPrice(label="Пополнение Stars", amount=amount * 100)]  # в копейках
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Пополнение баланса Stars",
        description=f"Пополнение на {amount} ⭐ для торговли акциями.",
        payload=f"topup_{amount}_{message.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="topup"
    )

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    amount_stars = message.successful_payment.total_amount // 100
    user_id = message.from_user.id
    # Добавляем звёзды пользователю
    supabase.rpc('add_stars', {'p_user_id': user_id, 'p_amount_stars': amount_stars}).execute()
    await message.answer(f"✅ Баланс пополнен на {amount_stars} ⭐. Теперь вы можете торговать!")

# Команда для вывода через подарки (пока заглушка)
@dp.message(Command("withdraw"))
async def withdraw_cmd(message: types.Message):
    await message.answer("Вывод средств через подарки (Gifts) будет доступен в ближайшее время. Вы сможете обменять Stars на подарки и продать их на внутреннем рынке.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
