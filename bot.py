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

# Переменные администратора (Задай их в Environment Variables на Render)
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")  

if not BOT_TOKEN or not GEMINI_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и GEMINI_API_KEY на Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Локальный файл для сохранения ID пользователей
USERS_FILE = "users.txt"

# Состояния FSM
class BotStates(StatesGroup):
    ai_mode = State()         # Режим общения с Gemini
    admin_broadcast = State() # Ожидание текста для рассылки
    admin_private_id = State() # Ожидание ID для личного ответа
    admin_private_msg = State() # Ожидание текста для личного ответа

# Используем стабильную версию v1 API, чтобы избежать частых ошибок 429 на хостингах
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (БАЗА ДАННЫХ В ТЕКСТОВОМ ФАЙЛЕ)
# ==============================================================================
def save_user(user_id: int):
    """Сохраняет ID пользователя, если его еще нет в файле"""
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
    """Возвращает количество уникальных пользователей"""
    if not os.path.exists(USERS_FILE):
        return 0
    with open(USERS_FILE, "r") as f:
        return len(f.read().splitlines())

def get_all_users() -> list:
    """Возвращает список всех ID пользователей"""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return f.read().splitlines()

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
    save_user(message.from_user.id)  # Сохраняем пользователя в файл
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

# ==============================================================================
# 4. ХЕНДЛЕРЫ АДМИН-ПАНЕЛИ (ДОСТУП ТОЛЬКО ДЛЯ ADMIN_ID)
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return  # Не реагируем, если пишет не админ
    await message.answer("🔑 Добро пожаловать в панель администратора, Босс!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Вышли из панели управления.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    count = get_users_count()
    await message.answer(f"📊 **Статистика бота:**\n\nВсего уникальных пользователей: `{count}`")

# --- МАССОВАЯ РАССЫЛКА ---
@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("📢 Введите текст сообщения для рассылки (или нажмите /cancel для отмены):")

@dp.message(BotStates.admin_broadcast, Command("cancel"))
async def admin_broadcast_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    if not users:
        await message.answer("База данных пуста. Некому отправлять.")
        return

    await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    success = 0
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05)  # Защита от лимитов отправки Telegram
        except Exception:
            pass  # Если пользователь заблокировал бота, просто идем дальше

    await message.answer(f"✅ Рассылка завершена!\nУспешно доставлено: {success}/{len(users)}", reply_markup=get_admin_keyboard())

# --- ОТПРАВКА ЛИЧНОГО СООБЩЕНИЯ ПО ID ---
@dp.message(F.text == "✉️ Написать пользователю")
async def admin_private_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_private_id)
    await message.answer("👤 Введите Telegram ID пользователя, которому хотите написать:")

@dp.message(BotStates.admin_private_id)
async def admin_private_id_rcv(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID должен состоять только из цифр. Попробуйте еще раз:")
        return
    await state.update_data(target_id=int(message.text))
    await state.set_state(BotStates.admin_private_msg)
    await message.answer(f"Отлично. Теперь напишите текст сообщения для ID `{message.text}`:")

@dp.message(BotStates.admin_private_msg)
async def admin_private_msg_exec(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_id")
    await state.clear()
    
    try:
        await bot.send_message(chat_id=target_id, text=f"💬 **Сообщение от администратора:**\n\n{message.text}")
        await message.answer("✅ Сообщение успешно отправлено!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение: {e}", reply_markup=get_admin_keyboard())

# --- СКАЧИВАНИЕ ФАЙЛА БАЗЫ ДАННЫХ ---
@dp.message(F.text == "📁 Скачать базу users.txt")
async def admin_download_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(USERS_FILE):
        file = types.FSInputFile(USERS_FILE)
        await message.answer_document(file, caption="Бэкап файла уникальных пользователей")
    else:
        await message.answer("Файл базы данных еще не создан.")

# ==============================================================================
# 5. ХЕНДЛЕР ОБРАБОТКИ GEMINI 2.5 FLASH ИИ
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text: return
    
    # Отправляем статус "печать", пока ожидаем ответ от Google
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Структура JSON тела запроса для Google API
    payload = {"contents": [{"parts": [{"text": message.text}]}]}

    try:
        async with ClientSession() as session:
            async with session.post(GEMINI_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    ai_text = data['candidates'][0]['content']['parts'][0]['text']
                    await message.answer(ai_text)
                elif response.status == 429:
                    await message.answer("⚠️ Ошибка 429 (Превышена квота). Google временно ограничил этот запрос. Пожалуйста, подождите минуту и повторите.")
                elif response.status in [400, 404]:
                    await message.answer("⚠️ Ошибка API (Неверный ключ). Проверь переменную GEMINI_API_KEY на Render!")
                else:
                    await message.answer(f"⚠️ Сервер Google вернул ошибку с кодом: {response.status}")
    except Exception as e:
        print(f"Ошибка HTTP-запроса к Gemini: {e}", file=sys.stderr)
        await message.answer("⚠️ Не удалось получить ответ от нейросети. Попробуйте позже.")

# ==============================================================================
# 6. ВЕБ-СЕРВЕР И ЗАПУСК
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот и Админ-панель успешно запущены внутри Docker!", status=200)

async def main():
    # Поднимаем aiohttp веб-сервер для успешного прохождения Port Scan на Render
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=PORT)
    await site.start()

    print("Запуск Телеграм бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
