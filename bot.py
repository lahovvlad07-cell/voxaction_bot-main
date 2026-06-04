import os
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
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-bot.vercel.app")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_URL and SUPABASE_KEY must be set")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN must be set")
if not WEBHOOK_URL:
    raise ValueError("❌ WEBHOOK_URL must be set")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def send_notification(user_id: int, message: str, notify_type: str):
    result = supabase.table('users').select(notify_type).eq('id', user_id).execute()
    if result.data and result.data[0].get(notify_type, True):
        try:
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление {user_id}: {e}")

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

@app.post("/trade-notification")
async def trade_notification(request: Request):
    data = await request.json()
    buyer_id = data.get('buyer_id')
    seller_id = data.get('seller_id')
    amount = data.get('amount')
    price = data.get('price')
    total = data.get('total')
    await send_notification(buyer_id, f"🎉 Вы купили {amount} акций по {price} ⭐ на сумму {total} ⭐. Сделка завершена!", "notify_trades")
    await send_notification(seller_id, f"💰 Вы продали {amount} акций по {price} ⭐ на сумму {total} ⭐. Средства зачислены!", "notify_trades")
    return {"ok": True}

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
    amount_stars = message.successful_payment.total_amount
    user_id = message.from_user.id
    supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + ?', amount_stars)}).eq('id', user_id).execute()
    await send_notification(user_id, f"✅ Баланс пополнен на {amount_stars} ⭐", "notify_topup")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
