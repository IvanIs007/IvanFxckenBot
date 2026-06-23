import os
import sys
import asyncio
import random
import json
import base64
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web, ClientSession, ClientTimeout

# ==============================================================================
# 1. КОНФИГУРАЦИЯ И ИНИЦИАЛИЗАЦИЯ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"
ADMIN_FILE = "admin_config.txt"
MAP_FILE = "chats_map.json"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_init_chat_id = State()
    admin_init_chat_msg = State()

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

MODELS_DATABASE = {
    "openrouter/free": "🤖 Автовыбор OpenRouter",
    "google/gemma-4-31b-it:free": "🧠 Google Gemma 4 31B IT",
    "openrouter/owl-alpha": "🦉 Owl Alpha (Agentic)",
    "nvidia/nemotron-3-ultra:free": "⚡ Nemotron 3 Ultra",
    "openai/gpt-oss-120b:free": "🌌 OpenAI gpt-oss-120b"
}

# ==============================================================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С МЕДИА И БАЗОЙ
# ==============================================================================
async def download_file_as_base64(file_id: str) -> str:
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        async with ClientSession() as session:
            async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}") as resp:
                if resp.status == 200:
                    file_bytes = await resp.read()
                    return base64.b64encode(file_bytes).decode('utf-8')
    except Exception as e:
        print(f"Ошибка кодирования файла в Base64: {e}")
    return ""

def load_msg_map() -> dict:
    if os.path.exists(MAP_FILE):
        try:
            with open(MAP_FILE, "r") as f: return json.load(f)
        except Exception: return {"to_admin": {}, "to_user": {}}
    return {"to_admin": {}, "to_user": {}}

def save_msg_map(data: dict):
    with open(MAP_FILE, "w") as f: json.dump(data, f, indent=4)

def register_msg_relation(user_chat_id: int, user_msg_id: int, admin_msg_id: int):
    data = load_msg_map()
    data["to_user"][str(admin_msg_id)] = {"chat_id": user_chat_id, "msg_id": user_msg_id}
    data["to_admin"][f"{user_chat_id}_{user_msg_id}"] = admin_msg_id
    save_msg_map(data)

def get_destination_by_admin_reply(admin_reply_to_msg_id: int) -> dict:
    data = load_msg_map()
    return data["to_user"].get(str(admin_reply_to_msg_id))

def get_admin_msg_id_by_user_reply(user_chat_id: int, user_reply_to_msg_id: int) -> int:
    data = load_msg_map()
    return data["to_admin"].get(f"{user_chat_id}_{user_reply_to_msg_id}")

async def set_bot_commands(user_id: int, is_adm: bool):
    commands = [
        types.BotCommand(command="start", description="🚀 Перезапустить бота"),
        types.BotCommand(command="ai", description="🤖 Режим нейросети"),
        types.BotCommand(command="dice", description="🎲 Игра в кости"),
    ]
    if is_adm: commands.append(types.BotCommand(command="admin", description="🔑 Панель управления"))
    try: await bot.set_my_commands(commands, scope=types.BotCommandScopeChat(chat_id=user_id))
    except Exception: pass

def get_or_set_admin(user_id: int) -> int:
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            c = f.read().strip()
            if c.isdigit(): return int(c)
    with open(ADMIN_FILE, "w") as f: f.write(str(user_id))
    return user_id

def is_admin(user_id: int) -> bool:
    if not os.path.exists(ADMIN_FILE): return False
    with open(ADMIN_FILE, "r") as f:
        c = f.read().strip()
        return c.isdigit() and int(c) == user_id

def get_admin_id() -> int:
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            c = f.read().strip()
            if c.isdigit(): return int(c)
    return 0

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
        [types.KeyboardButton(text="🤖 Общение с ИИ"), types.KeyboardButton(text="🎲 Сыграть в кости")]
    ]
    if is_admin(user_id): buttons.append([types.KeyboardButton(text="🔑 Админ Панель")])
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
        [types.KeyboardButton(text="👤 Написать первому"), types.KeyboardButton(text="🚪 Выйти")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==============================================================================
# 4. СИНХРОННЫЙ ДИАЛОГ С АДМИНОМ (РЕПЛАИ И МОСТ)
# ==============================================================================

# ИСПРАВЛЕНО: Вместо BotStates.ai_mode == None используем корректный StateFilter(None)
@dp.message(F.chat.type == "private", ~F.text.startswith("/"), lambda msg: not is_admin(msg.from_user.id))
async def handle_user_chat_to_admin(message: types.Message, state: FSMContext):
    # Проверяем состояние вручную во избежание конфликтов типов
    current_state = await state.get_state()
    if current_state == BotStates.ai_mode.state:
        return # Если юзер общается с ИИ, в админку слать не нужно

    adm_id = get_admin_id()
    if not adm_id: return

    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    header = f"📬 **Сообщение от:** {message.from_user.full_name} ({username})\n🆔 ID: `{message.from_user.id}`\n\n"
    
    target_reply_id = None
    if message.reply_to_message:
        target_reply_id = get_admin_msg_id_by_user_reply(message.chat.id, message.reply_to_message.message_id)

    try:
        if message.text:
            adm_msg = await bot.send_message(chat_id=adm_id, text=f"{header}{message.text}", reply_to_message_id=target_reply_id, parse_mode="Markdown")
        else:
            adm_msg = await bot.copy_message(chat_id=adm_id, from_chat_id=message.chat.id, message_id=message.message_id, caption=f"{header}{(message.caption or '')}", reply_to_message_id=target_reply_id, parse_mode="Markdown")
        register_msg_relation(message.chat.id, message.message_id, adm_msg.message_id)
    except Exception as e: print(f"Ошибка пересылки: {e}")

@dp.message(F.chat.type == "private", F.reply_to_message)
async def handle_admin_reply_to_user(message: types.Message):
    if not is_admin(message.from_user.id): return
    destination = get_destination_by_admin_reply(message.reply_to_message.message_id)
    if not destination: return
        
    user_chat_id = destination["chat_id"]
    user_orig_msg_id = destination["msg_id"]
    
    try:
        if message.text:
            user_msg = await bot.send_message(chat_id=user_chat_id, text=message.text, reply_to_message_id=user_orig_msg_id)
        else:
            user_msg = await bot.copy_message(chat_id=user_chat_id, from_chat_id=message.chat.id, message_id=message.message_id, reply_to_message_id=user_orig_msg_id)
        register_msg_relation(user_chat_id, user_msg.message_id, message.message_id)
    except Exception as e: await message.answer(f"❌ Ошибка отправки: {e}")

# ==============================================================================
# 5. СТАНДАРТНЫЕ КОМАНДЫ И АДМИНКА
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    current_admin = get_or_set_admin(message.from_user.id)
    adm_status = (current_admin == message.from_user.id)
    await set_bot_commands(message.from_user.id, adm_status)
    
    welcome = "👋 Привет! Я твой мультифункциональный бот.\nВ режиме ИИ я умею распознавать текст, рассматривать фото, кружочки и слушать голосовые!"
    if adm_status: welcome += "\n\n🔑 Ты администратор системы. Команда `/admin` доступна в меню."
    await message.answer(welcome, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

@dp.message(Command("dice"))
@dp.message(F.text == "🎲 Сыграть в кости")
async def handle_dice(message: types.Message):
    await message.answer("🎲 Мой бросок:")
    bot_msg = await message.answer_dice()
    await asyncio.sleep(4)
    await message.answer("🎲 Твой бросок:")
    user_msg = await message.answer_dice()
    await asyncio.sleep(4)
    res = f"🤖 ИИ: **{bot_msg.dice.value}** vs 👤 Ты: **{user_msg.dice.value}**\n\n"
    if bot_msg.dice.value > user_msg.dice.value: res += "Я победил! Слава машинам! 🦾"
    elif user_msg.dice.value > bot_msg.dice.value: res += "Ух ты, победа за тобой! 🎉"
    else: res += "Ничья! 🤝"
    await message.answer(res, parse_mode="Markdown")

@dp.message(Command("admin"))
@dp.message(F.text == "🔑 Админ Панель")
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🔑 Панель управления открыта!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти")
async def exit_admin(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("Вы вышли из панели управления.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer(f"📊 **Всего юзеров в базе:** `{len(get_all_users())}`", parse_mode="Markdown")

@dp.message(F.text == "👤 Написать первому")
async def admin_choose_user_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    users = get_all_users()
    if not users: return
    builder = InlineKeyboardBuilder()
    for u_id in users[-10:]: builder.button(text=f"Юзер {u_id}", callback_data=f"init_{u_id}")
    builder.adjust(1)
    await message.answer("Выберите пользователя или введите его ID вручную:", reply_markup=builder.as_markup())
    await state.set_state(BotStates.admin_init_chat_id)

@dp.message(BotStates.admin_init_chat_id)
async def admin_get_custom_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(chosen_id=message.text)
    await state.set_state(BotStates.admin_init_chat_msg)
    await message.answer(f"Напишите первое сообщение для пользователя `{message.text}`:")

@dp.callback_query(F.data.startswith("init_"))
async def admin_callback_init_id(callback: types.CallbackQuery, state: FSMContext):
    u_id = callback.data.split("_")[1]
    await state.update_data(chosen_id=u_id)
    await state.set_state(BotStates.admin_init_chat_msg)
    await callback.message.answer(f"Выбран пользователь `{u_id}`. Напишите сообщение:")
    await callback.answer()

@dp.message(BotStates.admin_init_chat_msg)
async def admin_send_init_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    u_id = int(data.get("chosen_id"))
    await state.clear()
    try:
        user_msg = await bot.send_message(chat_id=u_id, text=f"✉️ **Сообщение от администратора:**\n\n{message.text}", parse_mode="Markdown")
        register_msg_relation(u_id, user_msg.message_id, message.message_id)
        await message.answer("✅ Сообщение доставлено!")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")
    await message.answer("Возврат в меню панели:", reply_markup=get_admin_keyboard())

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
# 6. УЛЬТРА-ОБРАБОТЧИК ИИ (ИСПРАВЛЕННЫЙ)
# ==============================================================================
@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    data = await state.get_data()
    model = data.get("current_model", "openrouter/free")
    await message.answer(f"🤖 Режим ИИ запущен!\nПрисылайте текст, фотографии, видео или голосовые.", reply_markup=get_ai_keyboard())

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
    await callback.message.edit_text(f"✅ Модель обновлена: **{MODELS_DATABASE[full]}**")
    await callback.answer()

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(BotStates.ai_mode)
async def ai_multimedia_handler(message: types.Message, state: FSMContext):
    if message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    status_msg = await message.answer("⚡ *Считываю входящие данные...* 🔍", parse_mode="Markdown")

    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    prompt_text = message.text or message.caption or "Опиши и проанализируй этот файл."
    base64_image = ""

    # 1. ФОТО
    if message.photo:
        await status_msg.edit_text("📸 *Обрабатываю изображение...* ⚙️", parse_mode="Markdown")
        base64_image = await download_file_as_base64(message.photo[-1].file_id)

    # 2. КРУЖОЧКИ И ВИДЕО
    elif message.video or message.video_note:
        await status_msg.edit_text("🎬 *Анализирую кадры видео...* ⚙️", parse_mode="Markdown")
        file_id = None
        if message.video and message.video.thumb:
            file_id = message.video.thumb.file_id
        elif message.video_note and message.video_note.thumbnail:
            file_id = message.video_note.thumbnail.file_id
            
        if file_id:
            base64_image = await download_file_as_base64(file_id)
        else:
            await status_msg.edit_text("⚠️ Не удалось извлечь кадры видео. Попробуйте сменить модель.")
            return

    # 3. ГОЛОСОВЫЕ
    elif message.voice:
        await status_msg.edit_text("🎙 *Слушаю голосовое сообщение...* 💬", parse_mode="Markdown")
        prompt_text = f"[Голосовое сообщение]: Ответь пользователю на его аудио-запрос."

    # Нагрузка
    content_payload = [{"type": "text", "text": prompt_text}]
    if base64_image:
        content_payload.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        })

    payload = {
        "model": chosen_model, 
        "messages": [{"role": "user", "content": content_payload}],
        "stream": True  
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    full_response = ""
    last_text = ""
    update_interval = 0.6 
    last_update_time = asyncio.get_event_loop().time()
    cursors = [" ⏳", " ⚡", " 🤖", " ●"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=None)) as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers) as response:
                if response.status != 200:
                    await status_msg.edit_text("⚠️ Ошибка OpenRouter. Выберите другую модель.")
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
                        if current_time - last_update_time > update_interval:
                            animated_text = full_response + random.choice(cursors)
                            if animated_text.strip() != last_text:
                                try:
                                    await status_msg.edit_text(animated_text[:4000], parse_mode="Markdown")
                                    last_text = animated_text.strip()
                                    last_update_time = current_time
                                except Exception:
                                    try: await status_msg.edit_text(animated_text[:4000])
                                    except Exception: pass
                    except Exception: continue

        if full_response.strip():
            try: await status_msg.edit_text(full_response, parse_mode="Markdown")
            except Exception: await status_msg.edit_text(full_response)
        else:
            await status_msg.edit_text("⚠️ Не удалось получить ответ от ИИ.")
    except Exception:
        await status_msg.edit_text("⚠️ Ошибка сети при генерации.")

# ==============================================================================
# 7. ВЕБ-СЕРВЕР И СТАРТ
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
