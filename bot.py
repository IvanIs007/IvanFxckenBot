import os
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession

# Настройки
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotStates(StatesGroup):
    ai_mode = State()

# ПРЯМОЙ ВЫЗОВ ЧЕРЕЗ STABLE-PROXY
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("Привет! Нажми 'Общение с ИИ', чтобы начать.")

@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    await message.answer("Режим ИИ включен. Задавай вопрос:")

@dp.message(BotStates.ai_mode)
async def chat_ai(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    
    # Пытаемся отправить запрос с правильными заголовками
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_KEY}
    payload = {"contents": [{"parts": [{"text": message.text}]}]}
    
    try:
        async with ClientSession() as session:
            async with session.post(API_URL, json=payload, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    await message.answer(text)
                else:
                    await message.answer(f"Ошибка {resp.status}. Ключ отклонен.")
    except Exception as e:
        await message.answer("Ошибка связи с сервером.")

# Запуск
async def main():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Бот работает"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
