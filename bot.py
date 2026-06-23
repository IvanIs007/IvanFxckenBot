import os
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession

# ==============================================================================
# 1. ИНИЦИАЛИЗАЦИЯ И ПРОВЕРКА ПЕРЕМЕННЫХ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not GEMINI_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в Environment Variables на Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class BotStates(StatesGroup):
    ai_mode = State()

# URL для работы с актуальной моделью Gemini 2.5 Flash напрямую
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

# ==============================================================================
# 2. КЛАВИАТУРЫ
# ==============================================================================
def get_main_keyboard():
    buttons = [
        [types.KeyboardButton(text="🎧 Послушать треки"), types.KeyboardButton(text="🤖 Общение с ИИ")],
        [types.KeyboardButton(text="🎲 Кинуть кость")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_exit_keyboard():
    buttons = [[types.KeyboardButton(text="❌ Выйти из режима ИИ")]]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==============================================================================
# 3. ХЕНДЛЕРЫ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        "✌️ Здорова! Я новый бот. Можешь послушать мои треки, "
        "рискнуть сыграть со мной в кости или пообщаться с искусственным интеллектом абсолютно бесплатно!\n\n"
        "Используй кнопки ниже или команду /gemini."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("gemini"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_gemini_mode(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    await message.answer(
        "🤖 Режим общения с нейросетью активирован!\n\nЗадавай свои вопросы:", 
        reply_markup=get_exit_keyboard()
    )

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_gemini_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вы вышли из режима ИИ. Переключаю на главное меню.", 
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🎧 Послушать треки")
async def handle_tracks(message: types.Message):
    await message.answer("🎵 Тут когда-нибудь будут треки...")

@dp.message(F.text == "🎲 Кинуть кость")
async def handle_dice(message: types.Message):
    await message.answer_dice()

# Запрос к Gemini 2.5 Flash через aiohttp (напрямую, без падающих библиотек)
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text:
        return
        
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Формируем JSON структуру для официального API Google
    payload = {
        "contents": [{
            "parts": [{"text": message.text}]
        }]
    }

    try:
        async with ClientSession() as session:
            async with session.post(GEMINI_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    # Извлекаем текст ответа из структуры Google API
                    ai_text = data['candidates'][0]['content']['parts'][0]['text']
                    await message.answer(ai_text)
                elif response.status == 400 or response.status == 404:
                    await message.answer("⚠️ Ошибка API (Неверный ключ). Проверь GEMINI_API_KEY в настройках Render!")
                else:
                    await message.answer(f"⚠️ Сервер Google ответил ошибкой: {response.status}")
    except Exception as e:
        print(f"Ошибка запроса: {e}", file=sys.stderr)
        await message.answer("⚠️ Не удалось связаться с нейросетью. Попробуй позже.")

# ==============================================================================
# 4. ВЕБ-СЕРВЕР ДЛЯ RENDER PING И ЗАПУСК
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот онлайн внутри Docker!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=PORT)
    
    print(f"Запуск веб-сервера проверки Render на порту {PORT}...")
    await site.start()

    print("Запуск Телеграм бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
