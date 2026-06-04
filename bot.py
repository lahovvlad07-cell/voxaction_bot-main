import asyncio
import os
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# ---------- Flask сервер для Render ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot is running", 200

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

# ---------- Telegram бот ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://voxaction-bot.vercel.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть биржу", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Добро пожаловать в биржу акций!", reply_markup=kb)

async def main():
    # Запускаем Flask в отдельном потоке
    Thread(target=run_flask, daemon=True).start()
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
