import os
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web, ClientSession

# ==============================================================================
# 1. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь токена в Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"

# Состояния FSM
class BotStates(StatesGroup):
    ai_mode = State()         
    admin_main = State()
    admin_broadcast = State() 
    admin_private_id = State()
    admin_private_msg = State()

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Полная база бесплатных моделей из предоставленного списка
MODELS_DATABASE = {
    "openrouter/free": "🤖 Автовыбор ИИ",
    "google/gemma-4-31b:free": "🧠 Gemma 4 31B",
    "openai/gpt-oss-120b:free": "🌌 GPT-OSS 120B",
    "openai/gpt-oss-20b:free": "🌠 GPT-OSS 20B",
    "deepseek/deepseek-r1:free": "🧐 DeepSeek R1",
    "deepseek/deepseek-chat-v3:free": "💬 DeepSeek V3 Chat",
    "deepseek/deepseek-v3-base:free": "🧱 DeepSeek V3 Base",
    "nvidia/nemotron-3-ultra:free": "⚡ Nemotron Ultra",
    "nvidia/nemotron-3-super:free": "💥 Nemotron Super",
    "nvidia/nemotron-3-nano-30b-a3b:free": "📟 Nemotron 30B",
    "nvidia/nemotron-nano-9b-v2:free": "📲 Nemotron 9B",
    "cohere/north-mini-code:free": "💻 Cohere Code",
    "qwen/qwen2.5-vl-3b-instruct:free": "👁 Qwen 2.5 VL",
    "openrouter/owl-alpha": "🦉 Owl Alpha",
    "nex-agi/nex-n2-pro:free": "🚀 Nex N2 Pro",
    "stepfun/step-3.5-flash:free": "🏃 Step 3.5 Flash",
    "openrouter/optimus-alpha": "🎯 Optimus Alpha",
    "openrouter/quasar-alpha": "🔮 Quasar Alpha"
}

# ==============================================================================
# 2. РАБОТА С БАЗОЙ ДАННЫХ
# ==============================================================================
def save_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f: f.write(f"{user_id}\n")
        return
    with open(USERS_FILE, "r") as f: users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f: f.write(f"{user_id}\n")

def get_users_count() -> int:
    if not os.path.exists(USERS_FILE): return 0
    with open(USERS_FILE, "r") as f: return len(f.read().splitlines())

def get_all_users() -> list:
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return f.read().splitlines()

# ==============================================================================
# 3. ГЕНЕРАЦИЯ КЛАВИАТУР
# ==============================================================================
def get_main_keyboard():
    buttons = [
        [types.KeyboardButton(text="🎧 Послушать треки"), types.KeyboardButton(text="🤖 Общение с ИИ")],
        [types.KeyboardButton(text="🎲 Кинуть кость")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_ai_keyboard():
    buttons = [
        [types.KeyboardButton(text="⚙️ Выбрать нейросеть")],
        [types.KeyboardButton(text="❌ Выйти из режима ИИ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка всем")],
        [types.KeyboardButton(text="👤 Личное сообщение"), types.KeyboardButton(text="🚪 Выйти из админки")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Пагинация для inline-выбора моделей (по 6 штук на страницу)
def get_models_inline_keyboard(page: int = 0):
    builder = InlineKeyboardBuilder()
    items = list(MODELS_DATABASE.items())
    per_page = 6
    start = page * per_page
    end = start + per_page
    
    for model_id, name in items[start:end]:
        builder.button(text=name, callback_data=f"setmod_{model_id[:20]}_{page}") # Обрезаем id для лимита байт
    
    builder.adjust(2) # По 2 кнопки в ряд
    
    # Навигационные кнопки
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"aipage_{page-1}"))
    if end < len(items):
        nav_buttons.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"aipage_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
        
    return builder.as_markup()

# ==============================================================================
# 4. ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ И КОМАНДЫ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)  
    await message.answer(
        "✌️ Здорова! Я многофункциональный бот.\n"
        "Жми **🤖 Общение с ИИ**, чтобы открыть доступ к 15+ бесплатным нейросетям!",
        reply_markup=get_main_keyboard(), parse_mode="Markdown"
    )

@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai_mode(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    data = await state.get_data()
    current_model = data.get("current_model", "openrouter/free")
    model_name = MODELS_DATABASE.get(current_model, "Автовыбор")
    
    await message.answer(
        f"🤖 **Режим ИИ активирован!**\n"
        f"Текущая модель: `{model_name}`\n\n"
        f"Вы можете изменить модель по кнопке ниже. Напишите ваш вопрос:",
        reply_markup=get_ai_keyboard(), parse_mode="Markdown"
    )

@dp.message(BotStates.ai_mode, F.text == "⚙️ Выбрать нейросеть")
async def show_models_menu(message: types.Message):
    await message.answer("Выберите нужную нейросеть из базы OpenRouter:", reply_markup=get_models_inline_keyboard(0))

@dp.callback_query(F.data.startswith("aipage_"))
async def process_model_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_models_inline_keyboard(page))
    await callback.answer()

@dp.callback_query(F.data.startswith("setmod_"))
async def process_set_model(callback: types.CallbackQuery, state: FSMContext):
    # Из-за лимитов callback_data ищем модель по частичному совпадению
    short_id = callback.data.split("_")[1]
    page = callback.data.split("_")[2]
    
    full_model_id = "openrouter/free"
    for m_id in MODELS_DATABASE.keys():
        if m_id.startswith(short_id):
            full_model_id = m_id
            break
            
    await state.update_data(current_model=full_model_id)
    model_name = MODELS_DATABASE[full_model_id]
    
    await callback.message.edit_text(f"✅ Успешно выбрана модель:\n**{model_name}**\n\nЗадавайте свои вопросы!")
    await callback.answer()

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎧 Послушать треки")
async def handle_tracks(message: types.Message):
    await message.answer("🎵 Тут когда-нибудь будут треки...")

@dp.message(F.text == "🎲 Кинуть кость")
async def handle_dice(message: types.Message):
    await message.answer_dice()

# ==============================================================================
# 5. ПАНЕЛЬ АДМИНИСТРАТОРА (РАСШИРЕННАЯ)
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return  
    await state.set_state(BotStates.admin_main)
    await message.answer("🔑 Панель администратора открыта, Босс!", reply_markup=get_admin_keyboard())

@dp.message(BotStates.admin_main, F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вышли из панели управления.", reply_markup=get_main_keyboard())

@dp.message(BotStates.admin_main, F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    count = get_users_count()
    await message.answer(f"📊 **Статистика бота:**\n\nВсего уникальных пользователей: `{count}`", parse_mode="Markdown")

# --- СЦЕНАРИЙ ОБЩЕЙ РАССЫЛКИ ---
@dp.message(BotStates.admin_main, F.text == "📢 Рассылка всем")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("Введите текст рассылки (или нажмите Назад/Отмена):", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(BotStates.admin_main)
        await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())
        return
        
    users = get_all_users()
    success, failed = 0, 0
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра Telegram
        except Exception:
            failed += 1
            
    await state.set_state(BotStates.admin_main)
    await message.answer(f"📢 **Рассылка завершена!**\n\nУспешно: `{success}`\nНе дошло (блок бота): `{failed}`", 
                         reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# --- СЦЕНАРИЙ ЛИЧНОГО СООБЩЕНИЯ ---
@dp.message(BotStates.admin_main, F.text == "👤 Личное сообщение")
async def admin_private_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.admin_private_id)
    await message.answer("Пришлите Telegram ID пользователя, которому хотите написать:", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_private_id)
async def admin_private_get_id(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(BotStates.admin_main)
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
    if not message.text.isdigit():
        await message.answer("ID должен состоять только из цифр. Попробуйте еще раз:")
        return
        
    await state.update_data(target_user_id=message.text)
    await state.set_state(BotStates.admin_private_msg)
    await message.answer(f"ID {message.text} принят. Теперь введите сообщение для отправки:")

@dp.message(BotStates.admin_private_msg)
async def admin_private_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = int(data.get("target_user_id"))
    
    try:
        await bot.send_message(chat_id=target_id, text=f"✉️ **Сообщение от администрации:**\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Сообщение успешно доставлено пользователю!")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение. Ошибка: {e}")
        
    await state.set_state(BotStates.admin_main)
    await message.answer("Возвращаю в меню админки.", reply_markup=get_admin_keyboard())

# ==============================================================================
# 6. ВЗАИМОДЕЙСТВИЕ С OPENROUTER
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message, state: FSMContext):
    if not message.text or message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return 
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    payload = {
        "model": chosen_model, 
        "messages": [{"role": "user", "content": message.text}]
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://render.com", 
        "X-Title": "Telegram Bot" 
    }

    try:
        async with ClientSession() as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=50) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        ai_text = data['choices'][0]['message']['content']
                        await message.answer(ai_text)
                    else:
                        await message.answer("⚠️ Нейросеть вернула пустой ответ. Переключите модель.")
                else:
                    error_data = await response.text()
                    await message.answer(f"⚠️ Ошибка OpenRouter (Код {response.status}). Смените модель.")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка сети. Попробуйте еще раз.")

# ==============================================================================
# 7. ЗАПУСК ВЕБ-СЕРВЕРА И БОТА
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот онлайн!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()

    print("Запуск Телеграм бота с расширенной базой моделей...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
