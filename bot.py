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
# 1. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Список доступных БЕСПЛАТНЫХ моделей для клавиатуры
AVAILABLE_MODELS = {
    "🤖 Автовыбор ИИ": "openrouter/free",
    "🦙 Llama 4 (Free)": "meta-llama/llama-4-scout:free",
    "🐉 Qwen 3 (Free)": "qwen/qwen3-next-80b-a3b-instruct:free",
    "🧠 DeepSeek R1": "deepseek/deepseek-r1:free"
}

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

def get_ai_menu_keyboard():
    # Кнопки выбора моделей + кнопка выхода
    buttons = [
        [types.KeyboardButton(text="🤖 Автовыбор ИИ"), types.KeyboardButton(text="🦙 Llama 4 (Free)")],
        [types.KeyboardButton(text="🐉 Qwen 3 (Free)"), types.KeyboardButton(text="🧠 DeepSeek R1")],
        [types.KeyboardButton(text="❌ Выйти из режима ИИ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка")],
        [types.KeyboardButton(text="🚪 Выйти из админки")]
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
        "Используй кнопки ниже или команду /ai."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai_mode(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    # По умолчанию ставим автовыбор бесплатной модели
    await state.update_data(current_model="openrouter/free")
    await message.answer(
        "🤖 Режим нейросети активирован!\n\n"
        "По умолчанию включен **Автовыбор ИИ** (система сама подберет свободную модель).\n"
        "Вы можете изменить модель, нажав на кнопки ниже. Задавайте свой вопрос:", 
        reply_markup=get_ai_menu_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard())

# Хендлер для переключения моделей на лету
@dp.message(BotStates.ai_mode, F.text.in_(AVAILABLE_MODELS.keys()))
async def change_ai_model(message: types.Message, state: FSMContext):
    selected_name = message.text
    model_id = AVAILABLE_MODELS[selected_name]
    
    await state.update_data(current_model=model_id)
    await message.answer(f"🔄 Переключил вас на модель: **{selected_name}**\nЖду ваш вопрос!", parse_mode="Markdown")

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

# ==============================================================================
# 6. ХЕНДЛЕР ДЛЯ РАБОТЫ С OPENROUTER API (ИСПРАВЛЕННЫЙ)
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message, state: FSMContext):  # Добавили state сюда!
    if not message.text or message.text == "❌ Выйти из режима ИИ": return 
    if message.text in AVAILABLE_MODELS.keys(): return # Игнорируем нажатия кнопок переключения
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Теперь безопасно берем выбранную модель из контекста состояния
    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    payload = {
        "model": chosen_model, 
        "messages": [
            {"role": "user", "content": message.text}
        ]
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://render.com", 
        "X-Title": "Telegram Bot" 
    }

    try:
        async with ClientSession() as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=45) as response:
                if response.status == 200:
                    data = await response.json()
                    # Проверяем, вернул ли OpenRouter текст ответа
                    if 'choices' in data and len(data['choices']) > 0:
                        ai_text = data['choices'][0]['message']['content']
                        await message.answer(ai_text)
                    else:
                        await message.answer("⚠️ Нейросеть вернула пустой ответ. Попробуйте еще раз.")
                else:
                    error_data = await response.text()
                    print(f"Ошибка OpenRouter API: {error_data}")
                    await message.answer(f"⚠️ Ошибка нейросети (Код {response.status}).")
    except Exception as e:
        print(f"Исключение при запросе: {e}")
        # Теперь бот напишет точную ошибку прямо в Телеграм, чтобы мы видели, что не так!
        await message.answer(f"⚠️ Ошибка отправки запроса к ИИ: {str(e)}")
# ==============================================================================
# 7. ВЕБ-СЕРВЕР ДЛЯ СТАБИЛЬНОСТИ НА RENDER
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот онлайн!", status=200)

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
