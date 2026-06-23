import os
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
# Импортируем новый официальный клиент Google
from google import genai
from google.genai import errors

# ==============================================================================
# 1. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  

if not BOT_TOKEN or not GEMINI_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализируем официальный клиент Google напрямую через ключ
ai_client = genai.Client(api_key=GEMINI_KEY)

USERS_FILE = "users.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_private_id = State() 
    admin_private_msg = State() 

# ==============================================================================
# 2. РАБОТА С БАЗОЙ ДАННЫХ
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
# 3. КЛАВИАТУРЫ
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
# 4. ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)  
    welcome_text = (
        "✌️ Здорова! Я новый бот. Можешь послушать мои треки, "
        "рискнуть сыграть со мной в кости или пообщаться с искусственным интеллектом бесплатно!\n\n"
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
# 5. ХЕНДЛЕРЫ АДМИН-ПАНЕЛИ
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return  
    await message.answer("🔑 Панель администратора открыта, Босс!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Вышли из панели управления.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    count = get_users_count()
    await message.answer(f"📊 **Статистика бота:**\n\nВсего уникальных пользователей: `{count}`")

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("📢 Введите текст для рассылки всем пользователям:")

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    if not users:
        await message.answer("База данных пуста.")
        return
    await message.answer(f"🚀 Начинаю рассылку для {len(users)} пользователей...")
    success = 0
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05)  
        except Exception: pass
    await message.answer(f"✅ Рассылка завершена! Успешно доставлено: [{success}/{len(users)}]", reply_markup=get_admin_keyboard())

# ==============================================================================
# 6. ОФИЦИАЛЬНЫЙ КЛИЕНТ GOOGLE GEMINI (БЕЗ ПОСРЕДНИКОВ И ПРОКСИ)
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text or message.text == "❌ Выйти из режима ИИ": return 
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        # Запускаем генерацию в отдельном потоке, так как метод синхронный в genai.Client
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=message.text,
            )
        )
        
        if response and response.text:
            await message.answer(response.text)
        else:
            await message.answer("⚠️ Пустой ответ от нейросети. Попробуйте перефразировать вопрос.")
            
    except errors.APIError as e:
        # Перехватываем официальные ошибки самого Google API
        print(f"Google API Error: {e}", file=sys.stderr)
        if "429" in str(e):
            await message.answer("⚠️ Превышен лимит запросов к ИИ. Подождите пару минут.")
        elif "403" in str(e) or "401" in str(e):
            await message.answer("⚠️ Ошибка авторизации. Проверьте правильность GEMINI_API_KEY в Render.")
        else:
            await message.answer(f"⚠️ Ошибка Google API: {e.message}")
    except Exception as e:
        print(f"Общая ошибка: {e}", file=sys.stderr)
        await message.answer("⚠️ Не удалось получить ответ. Попробуйте отправить сообщение еще раз.")

# ==============================================================================
# 7. ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ СТАБИЛЬНОСТИ НА RENDER
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот стабилен и работает на официальной SDK Google GenAI!", status=200)

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
