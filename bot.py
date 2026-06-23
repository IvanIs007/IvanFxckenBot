import os
import sys
import asyncio
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web, ClientSession, ClientTimeout

# ==============================================================================
# 1. КОНФИГУРАЦИЯ И ПЕРЕМЕННЫЕ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"
ADMIN_FILE = "admin_config.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_private_id = State()
    admin_private_msg = State()
    admin_reply_msg = State()  # Состояние быстрого ответа пользователю

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

MODELS_DATABASE = {
    "openrouter/free": "🤖 Автовыбор OpenRouter",
    "google/gemma-4-31b-it:free": "🧠 Google Gemma 4 31B IT",
    "openrouter/owl-alpha": "🦉 Owl Alpha (Agentic)",
    "nvidia/nemotron-3-ultra:free": "⚡ Nemotron 3 Ultra",
    "poolside/laguna-m1:free": "🌊 Poolside Laguna M.1",
    "nvidia/nemotron-3-super:free": "💥 Nemotron 3 Super",
    "openai/gpt-oss-120b:free": "🌌 OpenAI gpt-oss-120b"
}

# ==============================================================================
# 2. СИНХРОНИЗАЦИЯ КОМАНД И МЕНЮ
# ==============================================================================
async def set_bot_commands(user_id: int, is_adm: bool):
    """Динамически меняет список команд в меню Telegram кнопки (слева внизу)"""
    commands = [
        types.BotCommand(command="start", description="🚀 Перезапустить бота"),
        types.BotCommand(command="ai", description="🤖 Режим нейросети"),
        types.BotCommand(command="dice", description="🎲 Игра в кости"),
    ]
    if is_adm:
        commands.append(types.BotCommand(command="admin", description="🔑 Панель управления"))
    
    try:
        await bot.set_my_commands(commands, scope=types.BotCommandScopeChat(chat_id=user_id))
    except Exception:
        pass

def get_or_set_admin(user_id: int) -> int:
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            content = f.read().strip()
            if content.isdigit(): return int(content)
    with open(ADMIN_FILE, "w") as f:
        f.write(str(user_id))
    return user_id

def is_admin(user_id: int) -> bool:
    if not os.path.exists(ADMIN_FILE): return False
    with open(ADMIN_FILE, "r") as f:
        content = f.read().strip()
        return content.isdigit() and int(content) == user_id

def save_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f: f.write(f"{user_id}\n")
        return
    with open(USERS_FILE, "r") as f: users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f: f.write(f"{user_id}\n")

def get_all_users() -> list:
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return f.read().splitlines()

# ==============================================================================
# 3. КЛАВИАТУРЫ
# ==============================================================================
def get_main_keyboard(user_id: int):
    buttons = [
        [types.KeyboardButton(text="🤖 Общение с ИИ"), types.KeyboardButton(text="🎲 Сыграть в кости")],
        [types.KeyboardButton(text="✍️ Написать админу")]
    ]
    if is_admin(user_id):
        buttons.append([types.KeyboardButton(text="🔑 Админ Панель")])
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
        [types.KeyboardButton(text="👤 Выбрать юзера"), types.KeyboardButton(text="🚪 Выйти")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==============================================================================
# 4. ОБРАБОТКА ОСНОВНЫХ КОМАНД И ДИАЛОГОВ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    current_admin = get_or_set_admin(message.from_user.id)
    adm_status = (current_admin == message.from_user.id)
    
    await set_bot_commands(message.from_user.id, adm_status)
    
    welcome = "👋 Привет! Я твой прокачанный бот.\nСинхронизация меню завершена!"
    if adm_status:
        welcome += "\n\n🔑 **Ты зафиксирован как админ.** Команда `/admin` добавлена в меню!"
        
    await message.answer(welcome, reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(Command("dice"))
@dp.message(F.text == "🎲 Сыграть в кости")
async def handle_dice(message: types.Message):
    await message.answer("🎲 Мой бросок:")
    bot_msg = await message.answer_dice()
    await asyncio.sleep(4) 
    
    await message.answer("🎲 Твой бросок:")
    user_msg = await message.answer_dice()
    await asyncio.sleep(4)
    
    b, u = bot_msg.dice.value, user_msg.dice.value
    res = f"🤖 ИИ: **{b}** vs 👤 Ты: **{u}**\n\n"
    if b > u: res += random.choice(["Я победил! Слава машинам! 🦾", "Изи вин для ИИ! 😎"])
    elif u > b: res += random.choice(["Ух ты, победа за тобой! 🎉", "Кожаный мешок сегодня удачливее ✊"])
    else: res += "Ничья! Жмём руки 🤝"
    await message.answer(res, parse_mode="Markdown")

# --- ОБРАТНАЯ СВЯЗЬ С АДМИНОМ ---
@dp.message(F.text == "✍️ Написать админу")
async def ask_admin_start(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await message.answer("Ты сам администратор! Используй панель.")
        return
    await message.answer("📝 Напиши текст твоего обращения/вопроса, и админ сразу его получит:")
    await state.set_state(BotStates.admin_private_msg) # Временный перехват сообщения

@dp.message(BotStates.admin_private_msg)
async def forward_to_admin(message: types.Message, state: FSMContext):
    await state.clear()
    
    if not os.path.exists(ADMIN_FILE):
        await message.answer("Администратор бота ещё не зарегистрирован.")
        return
        
    with open(ADMIN_FILE, "r") as f:
        adm_id = int(f.read().strip())
        
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Ответить", callback_data=f"reply_to_{message.from_user.id}")
    
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    # Пересылаем сообщение админу
    await bot.send_message(
        chat_id=adm_id,
        text=f"📬 **Новое сообщение в поддержку!**\n\n"
             f"👤 От: {message.from_user.full_name} ({username})\n"
             f"🆔 ID: `{message.from_user.id}`\n"
             f"💬 Текст:\n_{message.text}_",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await message.answer("✅ Твоё сообщение отправлено! Администратор ответит в ближайшее время.")

# ==============================================================================
# 5. ДИНАМИЧЕСКАЯ АДМИНКА И БЫСТРЫЕ ОТВЕТЫ
# ==============================================================================
@dp.message(Command("admin"))
@dp.message(F.text == "🔑 Админ Панель")
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🔑 Панель управления открыта!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти")
async def exit_admin(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("Вы вышли из админки.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer(f"📊 **Всего юзеров в базе:** `{len(get_all_users())}`", parse_mode="Markdown")

# --- БЫСТРЫЙ ВЫБОР ЮЗЕРА ДЛЯ СВЯЗИ ---
@dp.message(F.text == "👤 Выбрать юзера")
async def choose_user_menu(message: types.Message):
    if not is_admin(message.from_user.id): return
    users = get_all_users()
    if not users:
        await message.answer("База данных пользователей пуста.")
        return
        
    builder = InlineKeyboardBuilder()
    # Показываем последние 10 пользователей для быстрого клика
    for u_id in users[-10:]:
        builder.button(text=f"Написать ID: {u_id}", callback_data=f"reply_to_{u_id}")
    builder.adjust(1)
    await message.answer("Выберите пользователя из списка последних активных:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("reply_to_"))
async def setup_reply_state(callback: types.CallbackQuery, state: FSMContext):
    target_id = callback.data.split("_")[2]
    await state.update_data(reply_target=target_id)
    await state.set_state(BotStates.admin_reply_msg)
    await callback.message.answer(f"✍️ Введите ответ для пользователя `{target_id}` (или нажмите /cancel для отмены):")
    await callback.answer()

@dp.message(BotStates.admin_reply_msg)
async def send_reply_from_admin(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
        
    data = await state.get_data()
    target_id = int(data.get("reply_target"))
    await state.clear()
    
    try:
        await bot.send_message(chat_id=target_id, text=f"✉️ **Ответ от администратора:**\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Ответ успешно доставлен!")
    except Exception as e:
        await message.answer(f"❌ Не доставлено. Ошибка: {e}")
    await message.answer("Панель админа:", reply_markup=get_admin_keyboard())

# --- МАССОВАЯ РАССЫЛКА ---
@dp.message(F.text == "📢 Рассылка всем")
async def broadcast_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("Введите текст рассылки (или /cancel):")

@dp.message(BotStates.admin_broadcast)
async def broadcast_exec(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
    await state.clear()
    users = get_all_users()
    s, f = 0, 0
    for u in users:
        try:
            await bot.send_message(chat_id=int(u), text=message.text)
            s += 1
            await asyncio.sleep(0.04)
        except Exception: f += 1
    await message.answer(f"📢 Выполнено!\nУспешно: `{s}`\nОшибок: `{f}`", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# ==============================================================================
# 6. РЕЖИМ ИИ И ПЛАВНАЯ КОСМЕТИЧЕСКАЯ АНИМАЦИЯ (STREAMING С КУРСOРОМ)
# ==============================================================================
@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    data = await state.get_data()
    model = data.get("current_model", "openrouter/free")
    await message.answer(f"🤖 Режим ИИ запущен!\nТекущая модель: `{MODELS_DATABASE.get(model)}`", reply_markup=get_ai_keyboard())

@dp.message(BotStates.ai_mode, F.text == "⚙️ Выбрать нейросеть")
async def select_ai_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for m_id, name in MODELS_DATABASE.items():
        short = m_id.replace("free", "").replace("/", "-")[:20]
        builder.button(text=name, callback_data=f"ai_{short}")
    builder.adjust(1)
    await message.answer("Выберите модель:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("ai_"))
async def save_ai_selection(callback: types.CallbackQuery, state: FSMContext):
    short = callback.data.split("_")[1]
    full = "openrouter/free"
    for m_id in MODELS_DATABASE.keys():
        if short in m_id.replace("free", "").replace("/", "-"):
            full = m_id
            break
    await state.update_data(current_model=full)
    await callback.message.edit_text(f"✅ Выбрана модель: **{MODELS_DATABASE[full]}**")
    await callback.answer()

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard(message.from_user.id))

# --- ПЛАВНАЯ АНИМАЦИЯ МЫШЛЕНИЯ ---
@dp.message(BotStates.ai_mode)
async def ai_streaming_handler(message: types.Message, state: FSMContext):
    if not message.text or message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    status_msg = await message.answer("⚡ *Думаю...* 🤖", parse_mode="Markdown")
    
    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    payload = {
        "model": chosen_model, 
        "messages": [{"role": "user", "content": message.text}],
        "stream": True  
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    full_response = ""
    last_text = ""
    update_interval = 0.5 # Интервал анимации в секундах
    last_update_time = asyncio.get_event_loop().time()
    
    # Косметические индикаторы прогресса
    cursors = [" ⏳", " ⚡", " 🤖", " ●"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=None)) as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers) as response:
                if response.status != 200:
                    await status_msg.edit_text("⚠️ Ошибка OpenRouter. Смените модель.")
                    return

                async for line in response.content:
                    if not line: continue
                    decoded = line.decode('utf-8').strip()
                    if not decoded.startswith("data:"): continue
                    cleaned = decoded[5:].strip()
                    if cleaned == "[DONE]": break
                        
                    try:
                        chunk = json.loads(cleaned)
                        content = chunk['choices'][0].get('delta', {}).get('content', '')
                        full_response += content
                        
                        current_time = asyncio.get_event_loop().time()
                        # Плавное обновление UI, чтобы не упереться в лимиты Telegram API
                        if current_time - last_update_time > update_interval:
                            animated_text = full_response + random.choice(cursors)
                            if animated_text.strip() != last_text:
                                try:
                                    await status_msg.edit_text(animated_text[:4000])
                                    last_text = animated_text.strip()
                                    last_update_time = current_time
                                except Exception: pass
                    except Exception: continue

        # Финальный красивый выгруз готового ответа без курсоров
        if full_response.strip():
            await status_msg.edit_text(full_response)
        else:
            await status_msg.edit_text("⚠️ Не удалось получить ответ.")
    except Exception:
        await status_msg.edit_text("⚠️ Произошла ошибка сети.")

# ==============================================================================
# 7. СТАРТ WEB-СЕРВЕРА
# ==============================================================================
async def handle_ping(request): return web.Response(text="Бот онлайн!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()
    try: await dp.start_polling(bot)
    finally: await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
