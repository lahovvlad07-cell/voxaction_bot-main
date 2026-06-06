import os
import re
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from supabase import create_client

logging.basicConfig(level=logging.INFO)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction.duckdns.org")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://voxaction.duckdns.org/webhook")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_URL and SUPABASE_KEY must be set")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN must be set")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === Уведомления ===
async def save_notification(user_id: int, message: str, notify_type: str = 'info'):
    try:
        supabase.table('notifications').insert({
            'user_id': user_id,
            'message': message,
            'type': notify_type,
            'is_read': False
        }).execute()
    except Exception as e:
        logging.warning(f"Не удалось сохранить уведомление в БД: {e}")
    result = supabase.table('users').select(notify_type).eq('id', user_id).execute()
    if result.data and result.data[0].get(notify_type, True):
        try:
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление {user_id}: {e}")

async def check_achievements(user_id: int):
    achievements = supabase.table('achievements').select('*').execute()
    if not achievements.data:
        return
    user_achievements = supabase.table('user_achievements').select('achievement_id').eq('user_id', user_id).execute()
    earned_ids = {a['achievement_id'] for a in user_achievements.data}
    user = supabase.table('users').select('shares, referral_count, total_topup').eq('id', user_id).execute()
    if not user.data:
        return
    user_data = user.data[0]
    shares_cents = user_data['shares']
    referrals = user_data.get('referral_count', 0)
    total_topup_cents = user_data.get('total_topup', 0)
    trades_count = supabase.table('trades').select('id', count='exact').or_(f"seller_id.eq.{user_id},buyer_id.eq.{user_id}").execute()
    trades_count = trades_count.count or 0

    for ach in achievements.data:
        if ach['id'] in earned_ids:
            continue
        condition_type = ach['condition_type']
        condition_value = ach['condition_value']
        earned = False
        if condition_type == 'trades_count' and trades_count >= condition_value:
            earned = True
        elif condition_type == 'shares_held' and shares_cents >= condition_value:
            earned = True
        elif condition_type == 'referrals_count' and referrals >= condition_value:
            earned = True
        elif condition_type == 'total_topup' and total_topup_cents >= condition_value:
            earned = True
        elif condition_type == 'all_achievements':
            all_other = [a for a in achievements.data if a['id'] != ach['id'] and a['condition_type'] != 'all_achievements']
            all_earned = all(
                supabase.table('user_achievements').select('id').eq('user_id', user_id).eq('achievement_id', o['id']).execute().data
                for o in all_other
            )
            earned = all_earned
        if earned:
            supabase.table('user_achievements').insert({'user_id': user_id, 'achievement_id': ach['id']}).execute()
            await save_notification(user_id, f"🏆 Новое достижение: {ach['name']}! {ach['description']}", "notify_trades")

# === FastAPI ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "ok"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.post("/create-invoice")
async def create_invoice(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    amount_stars = data.get('amount')
    if not user_id or not amount_stars:
        return {"ok": False, "error": "Missing data"}, 400
    try:
        amount_stars = int(amount_stars)
    except:
        return {"ok": False, "error": "Amount must be integer"}, 400
    if amount_stars < 1 or amount_stars > 10000:
        return {"ok": False, "error": "Amount must be 1–10000"}, 400
    try:
        invoice_link = await bot.create_invoice_link(
            title="Пополнение баланса",
            description=f"Пополнение на {amount_stars} ⭐",
            payload=f"topup_{amount_stars}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{amount_stars} Stars", "amount": amount_stars}]
        )
        return {"ok": True, "invoice_link": invoice_link}
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        return {"ok": False, "error": str(e)}, 500

@app.post("/update-ref-code")
async def update_referral_code(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    custom_code = data.get('custom_code', '').strip().lower()
    if not user_id:
        return {"ok": False, "error": "Missing user_id"}, 400
    if not custom_code or len(custom_code) > 32:
        return {"ok": False, "error": "Код должен быть от 1 до 32 символов"}, 400
    if not re.match(r'^[a-z0-9_]+$', custom_code):
        return {"ok": False, "error": "Используйте только латиницу, цифры и символ подчёркивания (_)"}, 400
    # Проверяем уникальность
    existing = supabase.table('users').select('id').eq('custom_ref_code', custom_code).execute()
    if existing.data:
        return {"ok": False, "error": "Этот код уже занят, выберите другой"}, 400
    # Обновляем
    supabase.table('users').update({'custom_ref_code': custom_code}).eq('id', user_id).execute()
    return {"ok": True, "custom_ref_code": custom_code}

@app.post("/trade-notification")
async def trade_notification(request: Request):
    data = await request.json()
    buyer_id = data.get('buyer_id')
    seller_id = data.get('seller_id')
    amount = data.get('amount')
    price = data.get('price')
    total = data.get('total')
    await save_notification(buyer_id, f"🎉 Вы купили {amount} акций по {price} ⭐ на сумму {total} ⭐. Сделка завершена!", "notify_trades")
    await save_notification(seller_id, f"💰 Вы продали {amount} акций по {price} ⭐ на сумму {total} ⭐. Средства зачислены!", "notify_trades")
    await check_achievements(buyer_id)
    await check_achievements(seller_id)
    return {"ok": True}

# ... (остальные админ-эндпоинты без изменений) ...
# (admin/stats, admin/users, admin/add-shares, admin/add-stars, admin/cancel-order)

# === Telegram handlers ===
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None
    user_id = message.from_user.id

    # Обработка реферального кода (поддерживает и стандартный REF..., и кастомный)
    if ref_code:
        # Ищем пользователя у которого либо referral_code == ref_code, либо custom_ref_code == ref_code
        referrer = supabase.table('users').select('id').eq('referral_code', ref_code).execute()
        if not referrer.data:
            referrer = supabase.table('users').select('id').eq('custom_ref_code', ref_code).execute()
        if referrer.data and referrer.data[0]['id'] != user_id:
            referrer_id = referrer.data[0]['id']
            current_user = supabase.table('users').select('referred_by').eq('id', user_id).execute()
            if not current_user.data or current_user.data[0].get('referred_by') is None:
                supabase.table('users').update({'referred_by': referrer_id}).eq('id', user_id).execute()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций! Переходите в приложение.", reply_markup=kb)

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment(message: types.Message):
    amount_stars = message.successful_payment.total_amount
    user_id = message.from_user.id

    user = supabase.table('users').select('stars_balance, total_topup').eq('id', user_id).execute()
    if user.data:
        new_balance = user.data[0]['stars_balance'] + amount_stars
        new_topup = (user.data[0]['total_topup'] or 0) + amount_stars * 100
        supabase.table('users').update({
            'stars_balance': new_balance,
            'total_topup': new_topup
        }).eq('id', user_id).execute()
    else:
        supabase.table('users').update({
            'stars_balance': amount_stars,
            'total_topup': amount_stars * 100
        }).eq('id', user_id).execute()

    await save_notification(user_id, f"✅ Баланс пополнен на {amount_stars} ⭐", "notify_topup")

    user_data = supabase.table('users').select('referred_by, referral_bonus_claimed').eq('id', user_id).execute()
    if user_data.data:
        referred_by = user_data.data[0].get('referred_by')
        bonus_claimed = user_data.data[0].get('referral_bonus_claimed', False)
        if referred_by and not bonus_claimed and amount_stars >= 10:
            referrer = supabase.table('users').select('shares, total_earned_shares').eq('id', referred_by).execute()
            if referrer.data:
                new_shares = referrer.data[0]['shares'] + 500
                new_total_earned = (referrer.data[0]['total_earned_shares'] or 0) + 500
                supabase.table('users').update({
                    'shares': new_shares,
                    'total_earned_shares': new_total_earned,
                    'referral_count': supabase.raw('referral_count + 1')
                }).eq('id', referred_by).execute()

                supabase.table('referrals').update({
                    'topup_completed': True,
                    'topup_amount_cents': amount_stars * 100,
                    'bonus_earned': True
                }).eq('referred_id', user_id).execute()

            supabase.table('users').update({'referral_bonus_claimed': True}).eq('id', user_id).execute()
            await save_notification(referred_by, f"🎉 Ваш друг @{message.from_user.username or user_id} пополнил баланс на {amount_stars} ⭐! Вы получили 5 акций.", "notify_referral")
            await check_achievements(referred_by)

    await check_achievements(user_id)

@dp.message(Command("withdraw_gifts"))
async def withdraw_gifts(message: types.Message):
    user_id = message.from_user.id
    user = supabase.table('users').select('stars_balance').eq('id', user_id).execute()
    if not user.data:
        await message.answer("❌ Пользователь не найден.")
        return
    balance = user.data[0]['stars_balance']
    if balance < 1000:
        await message.answer("❌ Минимальная сумма вывода – 1000 ⭐. У вас недостаточно средств.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1000 ⭐", callback_data="withdraw_1000"),
         InlineKeyboardButton(text="2000 ⭐", callback_data="withdraw_2000"),
         InlineKeyboardButton(text="5000 ⭐", callback_data="withdraw_5000")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="withdraw_cancel")]
    ])
    await message.answer("💸 Вывод через подарки (Gifts). Выберите сумму:", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("withdraw_"))
async def process_withdraw(callback: types.CallbackQuery):
    data = callback.data
    if data == "withdraw_cancel":
        await callback.message.edit_text("❌ Вывод отменён.")
        await callback.answer()
        return
    amount = int(data.split('_')[1])
    user_id = callback.from_user.id
    user = supabase.table('users').select('stars_balance').eq('id', user_id).execute()
    if not user.data or user.data[0]['stars_balance'] < amount:
        await callback.message.edit_text("❌ Недостаточно средств для вывода.")
        await callback.answer()
        return
    new_balance = user.data[0]['stars_balance'] - amount
    supabase.table('users').update({'stars_balance': new_balance}).eq('id', user_id).execute()
    await callback.message.edit_text(
        f"✅ Заявка на вывод {amount} ⭐ принята. Администратор свяжется с вами для отправки подарка.\n"
        f"Ваш баланс: {new_balance} ⭐"
    )
    await callback.answer()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
