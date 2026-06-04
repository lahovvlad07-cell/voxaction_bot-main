import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from aiogram.filters import Command, CommandStart
from supabase import create_client

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Инициализация бота и Supabase
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Хранилище реферальных кодов (в памяти, для быстроты)
referral_codes = {}

async def get_user(user_id):
    res = supabase.table('users').select('*').eq('id', user_id).execute()
    if res.data:
        return res.data[0]
    return None

async def create_user(user_id, username, ref_code=None):
    data = {
        'id': user_id,
        'username': username,
        'shares': 0,
        'stars_balance': 0,
        'hide_rating': False,
        'theme': 'light',
        'notifications_enabled': True,
        'referral_code': None
    }
    if ref_code:
        data['referred_by'] = ref_code
    supabase.table('users').insert(data).execute()
    # Генерируем реферальный код (в триггере БД, но можно и здесь)
    new_user = await get_user(user_id)
    if new_user and not new_user.get('referral_code'):
        ref = f"REF{user_id}"
        supabase.table('users').update({'referral_code': ref}).eq('id', user_id).execute()
    return await get_user(user_id)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None
    
    user = await get_user(user_id)
    if not user:
        user = await create_user(user_id, username, ref_code)
        # Если есть реферал, можно начислить бонусы
        if ref_code:
            referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
            if referrer.data:
                referrer_id = referrer.data[0]['id']
                # Начисляем бонус рефереру (например, 5 Stars)
                supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 500')}).eq('id', referrer_id).execute()
                supabase.table('notifications').insert({'user_id': referrer_id, 'text': f'Пользователь {username} зарегистрировался по вашей ссылке! Вы получили 5 ⭐'}).execute()
                # Бонус новому пользователю
                supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + 200')}).eq('id', user_id).execute()
                supabase.table('notifications').insert({'user_id': user_id, 'text': 'Вы получили 2 ⭐ за регистрацию по реферальной ссылке!'}).execute()
        else:
            # Обычная регистрация без бонуса
            pass
    else:
        # Если пользователь уже есть, просто приветствуем
        pass
    
    web_app_url = "https://voxaction-frontend.vercel.app"  # Замените на ваш реальный URL на Vercel
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🚀 Открыть биржу", web_app=types.WebAppInfo(url=web_app_url))]
    ])
    await message.answer(
        f"Добро пожаловать, {message.from_user.first_name}! Используйте кнопку ниже для входа в биржу акций.",
        reply_markup=kb
    )

@dp.message(Command("topup_10"))
async def topup_10(message: types.Message):
    prices = [LabeledPrice(label="Пополнение Stars (10 ⭐)", amount=1000)]  # 10 звезд = 1000 копеек
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Пополнение баланса",
        description="Пополните баланс Stars для торговли на бирже.",
        payload="topup_10",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="topup_10"
    )

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment_handler(message: types.Message):
    amount_stars = message.successful_payment.total_amount // 100  # из копеек в звёзды
    user_id = message.from_user.id
    # Обновляем баланс пользователя
    supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + ?', amount_stars)}).eq('id', user_id).execute()
    await message.answer(f"✅ Ваш баланс пополнен на {amount_stars} ⭐")

@dp.message(Command("withdraw"))
async def withdraw_cmd(message: types.Message):
    # Заглушка – позже можно реализовать вывод через подарки
    await message.answer("Функция вывода через подарки в разработке. Следите за обновлениями!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
