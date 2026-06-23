import os
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession

# --- Настройки ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotStates(StatesGroup):
    ai_mode = State()

# --- Кнопки ---
def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="🎧 Послушать треки"), types.KeyboardButton(text="🤖 Общение с ИИ")],
        [types.KeyboardButton(text="🎲 Кинуть кость")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_exit_keyboard():
    kb = [[types.KeyboardButton(text="❌ Выйти из режима ИИ")]]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- Хендлеры ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✌️ Бот перезапущен! Выбери действие:", reply_markup=get_main_keyboard())

@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    await message.answer("🤖 Режим ИИ активен. Жду твой вопрос:", reply_markup=get_exit_keyboard())

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вышел из режима ИИ.", reply_markup=get_main_keyboard())

@dp.message(BotStates.ai_mode)
async def chat_ai(message: types.Message):
    if not message.text: return
    await bot.send_chat_action(message.chat.id, "typing")
    
    # URL для запроса (официальный API)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {"contents": [{"parts": [{"text": message.text}]}]}
    
    try:
        async with ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    await message.answer(text)
                elif resp.status == 400:
                    await message.answer("⚠️ Ошибка: Проверь, правильно ли вставлен ключ в Render.")
                else:
                    await message.answer(f"⚠️ Ошибка сервера {resp.status}. Ключ AQ... может не подходить.")
    except Exception:
        await message.answer("⚠️ Ошибка подключения к Google.")

# --- Запуск ---
async def main():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Бот запущен"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
