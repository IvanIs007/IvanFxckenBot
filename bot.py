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
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  # Твой Telegram ID для админки

if not BOT_TOKEN or not GEMINI_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в Render!")
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

# ==============================================================================
# НАСТРОЙКА ССЫЛКИ CLOUDFLARE AI GATEWAY (ПОД ФОРМАТ COMPAT)
# ==============================================================================
# Используем ровно ту ссылку, которую сгенерировал Cloudflare. Ключ в неё зашивать не нужно!
GEMINI_PROXY_URL = "https://gateway.ai.cloudflare.com/v1/42b17838faa1c270c8974a82d80aba1b/my-gemini-bot/compat/chat/completions"

# ==============================================================================
# 2. РАБОТА С БАЗОЙ ДАННЫХ (ФАЙЛ)
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

@dp.message(F.text == "✉️ Написать пользователю")
async def admin_private_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_private_id)
    await message.answer("👤 Введите Telegram ID пользователя:")

@dp.message(BotStates.admin_private_id)
async def admin_private_id_rcv(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка: ID должен состоять только из цифр. Введите заново:")
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
        await message.answer("✅ Отправлено успешно!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить. Ошибка: {e}", reply_markup=get_admin_keyboard())

@dp.message(F.text == "📁 Скачать базу users.txt")
async def admin_download_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(USERS_FILE):
        await message.answer_document(types.FSInputFile(USERS_FILE), caption="Актуальный бэкап пользователей")
    else:
        await message.answer("База пользователей еще не создана.")

# ==============================================================================
# 6. ОБРАБОТКА ЗАПРОСОВ К GEMINI (ЧЕРЕЗ COMPAT СОВМЕСТИМОСТЬ CLOUDFLARE)
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message):
    if not message.text: return
    if message.text == "❌ Выйти из режима ИИ": return 
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Формат тела запроса под OpenAI-совместимый эндпоинт Cloudflare Gateway
    payload = {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": message.text}
        ]
    }
    
    # Передаем ваш ключ AQ... как Bearer токен в заголовке Authorization
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_KEY}"
    }

    try:
        async with ClientSession() as session:
            async with session.post(GEMINI_PROXY_URL, json=payload, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    # Извлекаем текст ответа по стандартам OpenAI Chat Completions
                    ai_text = data['choices'][0]['message']['content']
                    await message.answer(ai_text)
                elif response.status in [401, 403]:
                    await message.answer("⚠️ Ошибка авторизации. Проверь правильность токена GEMINI_API_KEY в Render. Он должен начинаться на AQ...")
                elif response.status == 429:
                    await message.answer("⚠️ Превышен лимит запросов (429). Подождите минуту.")
                else:
                    await message.answer(f"⚠️ Ошибка шлюза. Код ответа сервера Cloudflare: {response.status}")
    except Exception as e:
        print(f"Ошибка шлюза Cloudflare: {e}", file=sys.stderr)
        await message.answer("⚠️ Не удалось связаться с нейросетью. Попробуйте отправить сообщение еще раз.")

# ==============================================================================
# 7. ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ СТАБИЛЬНОСТИ НА RENDER (PING)
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот запущен и стабилен через Cloudflare Gateway COMPAT эндпоинт!", status=200)

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
