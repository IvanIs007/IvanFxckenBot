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
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  

if not BOT_TOKEN or not GEMINI_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в Environment Variables!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_private_id = State() 
    admin_private_msg = State() 

# Используем стабильный reverse-proxy эндпоинт для Gemini API
GEMINI_PROXY_URL = f"https://gateway.ai.cloudflare.com/v1/public/gemini/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

# Если верхний вариант будет сбоить, вот резервный стабильный шлюз (раскомментируй если что):
# GEMINI_PROXY_URL = f"https://gemini.api.proxy.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
# Для текущего решения используем чистый альтернативный прокси-базовый URL:
GEMINI_PROXY_URL = f"https://google-ai.chatgpt-proxy.workers.dev/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (БАЗА ДАННЫХ В ТЕКСТОВОМ ФАЙЛЕ)
# ==============================================================================
def save_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            f.write(f"{user_id}\n")
        return
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

def get_users_count() -> int:
    if not os.path.exists(USERS_FILE): return 0
    with open(USERS_FILE, "r") as f: return len(f.read().splitlines())

def get_all_users() -> list:
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return f.read().splitlines()

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

def get_admin_keyboard():
    buttons = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка")],
        [types.KeyboardButton(text="✉️ Написать пользователю")],
        [types.KeyboardButton(text="📁 Скачать базу users.txt"), types.KeyboardButton(text="🚪 Выйти из админки")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==============================================================================
# 3. ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)  
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
    await message.answer("🤖 Режим общения с нейросетью активирован!\n\nЗадавай свои вопросы:", reply_markup=get_exit_keyboard())

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_gemini_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ. Переключаю на главное меню.", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎧 Послушать треки")
async def handle_tracks(message: types.Message):
    await message.answer("🎵 Тут когда-нибудь будут треки...")

@dp.message(F.text == "🎲 Кинуть кость")
async def handle_dice(message: types.Message):
    await message.answer_dice()

# ==============================================================================
# 4. ХЕНДЛЕР АДМИНКИ
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return  
    await message.answer("🔑 Добро пожаловать в панель администратора, Босс!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Вышли из панели управления.", reply_markup=get_main_keyboard())

# ==============================================================================
# 5. ХЕНДЛЕР ОБРАБОТКИ GEMINI ЧЕРЕЗ REVERSE PROXY WOKRERS
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text: return
    if message.text == "❌ Выйти из режима ИИ": return # Даем отработать верхнему хендлеру
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    payload = {"contents": [{"parts": [{"text": message.text}]}]}

    try:
        async with ClientSession() as session:
            async with session.post(GEMINI_PROXY_URL, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    ai_text = data['candidates'][0]['content']['parts'][0]['text']
                    await message.answer(ai_text)
                elif response.status == 429:
                    await message.answer("⚠️ Выдано ограничение частоты запросов от Google (429). Подождите минуту.")
                elif response.status in [401, 403]:
                    await message.answer("⚠️ Ошибка авторизации. Проверьте правильность GEMINI_API_KEY в Render!")
                else:
                    await message.answer(f"⚠️ Шлюз вернул ошибку: {response.status}. Повторите запрос чуть позже.")
    except Exception as e:
        print(f"Ошибка шлюза: {e}", file=sys.stderr)
        await message.answer("⚠️ Не удалось получить ответ от ИИ. Попробуйте отправить сообщение еще раз.")

# ==============================================================================
# 6. ВЕБ-СЕРВЕР И ЗАПУСК
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот онлайн. Шлюз Gemini настроен через Reverse Proxy!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()

    print("Запуск Телеграм бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
