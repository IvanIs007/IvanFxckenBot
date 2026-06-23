import os
import sys
import asyncio
import urllib.parse
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

# Выведем в логи начало ключа для самопроверки (без полной утечки данных)
print(f"Бот запущен. Проверка ключа Gemini (первые 6 символов): {GEMINI_KEY[:6]}...")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_private_id = State() 
    admin_private_msg = State() 

# Формируем оригинальный URL и безопасно кодируем его для прокси-серверов
ORIGINAL_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
ENCODED_URL = urllib.parse.quote(ORIGINAL_URL, safe='')

# Список независимых прокси-шлюзов для обхода блокировки 429
PROXY_POOL = [
    f"https://api.allorigins.win/raw?url={ENCODED_URL}",
    f"https://corsproxy.io/?{urllib.parse.quote(ORIGINAL_URL)}"
]

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
# 4. ХЕНДЛЕРЫ АДМИН-ПАНЕЛИ
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return  
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

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("📢 Введите текст для рассылки (или /cancel):")

@dp.message(BotStates.admin_broadcast, Command("cancel"))
async def admin_broadcast_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    if not users:
        await message.answer("База данных пуста.")
        return
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    success = 0
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05)  
        except Exception: pass
    await message.answer(f"✅ Рассылка завершена! [{success}/{len(users)}]", reply_markup=get_admin_keyboard())

@dp.message(F.text == "✉️ Написать пользователю")
async def admin_private_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_private_id)
    await message.answer("👤 Введите Telegram ID пользователя:")

@dp.message(BotStates.admin_private_id)
async def admin_private_id_rcv(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Только цифры:")
        return
    await state.update_data(target_id=int(message.text))
    await state.set_state(BotStates.admin_private_msg)
    await message.answer(f"Напишите текст сообщения для ID `{message.text}`:")

@dp.message(BotStates.admin_private_msg)
async def admin_private_msg_exec(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_id")
    await state.clear()
    try:
        await bot.send_message(chat_id=target_id, text=f"💬 **Сообщение от администратора:**\n\n{message.text}")
        await message.answer("✅ Отправлено!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=get_admin_keyboard())

@dp.message(F.text == "📁 Скачать базу users.txt")
async def admin_download_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(USERS_FILE):
        await message.answer_document(types.FSInputFile(USERS_FILE), caption="Бэкап пользователей")
    else:
        await message.answer("База еще не создана.")

# ==============================================================================
# 5. ХЕНДЛЕР ОБРАБОТКИ GEMINI С ЗАЩИЩЕННЫМ URL КОДИРОВАНИЕМ
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text: return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    payload = {"contents": [{"parts": [{"text": message.text}]}]}

    for proxy_url in PROXY_POOL:
        try:
            async with ClientSession() as session:
                async with session.post(proxy_url, json=payload, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        ai_text = data['candidates'][0]['content']['parts'][0]['text']
                        await message.answer(ai_text)
                        return
                    else:
                        print(f"Лог: Прокси вернул статус {response.status}. Пробуем альтернативный...", file=sys.stderr)
        except Exception as e:
            print(f"Лог: Ошибка подключения к прокси: {e}", file=sys.stderr)
            continue

    await message.answer("⚠️ Сервер временного шлюза перегружен (429/401). Повторите попытку ввода через 15-30 секунд.")

# ==============================================================================
# 6. ВЕБ-СЕРВЕР И ЗАПУСК
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот стабилен и защищен от ошибок компиляции!", status=200)

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
