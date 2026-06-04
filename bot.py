# Добавьте импорты в начало файла
from flask import Flask, request, jsonify
from aiogram.types import LabeledPrice, PreCheckoutQuery, SuccessfulPayment
import asyncio
import os
import logging
from threading import Thread
from supabase import create_client

# ... (остальные импорты и переменные)

app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot is running", 200

# НОВЫЙ ЭНДПОЙНТ ДЛЯ СОЗДАНИЯ ИНВОЙСА
@app_flask.route('/create-invoice', methods=['POST'])
def create_invoice():
    data = request.get_json()
    telegram_id = data.get('user_id')
    amount = data.get('amount')  # в звёздах
    if not telegram_id or not amount:
        return jsonify({"ok": False, "error": "Missing user_id or amount"}), 400
    if amount < 1 or amount > 10000:
        return jsonify({"ok": False, "error": "Amount must be between 1 and 10000"}), 400
    # Создаём инвойс с помощью бота (синхронно в асинхронном окружении – можно через asyncio.run, но лучше сделать асинхронную функцию)
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
                prices=[LabeledPrice(label=f"{amount} Stars", amount=amount * 100)]  # amount в копейках
            )
        )
        loop.close()
        return jsonify({"ok": True, "invoice_link": invoice_link})
    except Exception as e:
        logging.error(f"Error creating invoice: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Убедитесь, что у вас есть обработчики pre_checkout_query и successful_payment
@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(SuccessfulPayment)
async def successful_payment(message: types.Message):
    amount_stars = message.successful_payment.total_amount // 100
    user_id = message.from_user.id
    supabase.table('users').update({'stars_balance': supabase.raw('stars_balance + ?', amount_stars)}).eq('id', user_id).execute()
    await message.answer(f"✅ Баланс пополнен на {amount_stars} ⭐")

# Запуск Flask в потоке (уже должно быть, но проверьте)
def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

# В функции main запускайте поток Flask
async def main():
    Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)
