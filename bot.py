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
# 1. КОНФИГУРАЦИЯ И МОДЕЛИ
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
HF_KEY = os.environ.get("HF_API_KEY", "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")
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в переменных среды!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"
ADMIN_FILE = "admin_config.txt"
MAP_FILE = "chats_map.json"

class BotStates(StatesGroup):
    ai_mode = State()         
    support_mode = State()     
    admin_broadcast = State()  
    admin_init_chat_id = State()
    admin_init_chat_msg = State()

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
HF_ENDPOINT = "https://api-inference.huggingface.co/v1/chat/completions"

# Разделенная база данных моделей по провайдерам
MODELS_DATABASE = {
    "openrouter": {
        "openrouter/auto": "🤖 Автовыбор OpenRouter [👁 Vision]",
        "google/gemma-4-31b-it:free": "🧠 Google Gemma 4 31B [👁 Vision]",
        "google/gemma-4-26b-a4b-it:free": "🧠 Google Gemma 4 26B [👁 Vision]",
        "bytedance-seed/seedream-4.5": "🔮 ByteDance Seedream 4.5 [👁 Vision]",
        "openrouter/owl-alpha": "🦉 Owl Alpha (Agentic)",
        "nvidia/nemotron-3-ultra-550b-a55b:free": "⚡ Nemotron 3 Ultra 550B",
        "openai/gpt-oss-20b:free": "🌌 OpenAI GPT OSS 20B",
        "openai/gpt-oss-120b:free": "🌌 OpenAI GPT OSS 120B",
        "nvidia/nemotron-3-super-120b-a12b:free": "💥 Nemotron 3 Super 120B",
        "nvidia/nemotron-nano-9b-v2:free": "🔋 Nemotron Nano 9B v2",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "🧩 Nemotron Omni Reasoning [🎙 Voice]",
        "cohere/north-mini-code:free": "💻 Cohere North Mini Code",
        "nvidia/nemotron-3-nano-30b-a3b:free": "🔋 Nemotron 3 Nano 30B"
    },
    "huggingface": {
        "hf/google/gemma-4-12B-it": "🧠 Gemma 4 12B (HF)",
        "hf/black-forest-labs/FLUX.2-dev": "🎨 FLUX.2 Dev [🎨 Создание Картинок]",
        "hf/deepseek-ai/DeepSeek-V4-Flash": "⚡ DeepSeek V4 Flash (HF)",
        "hf/microsoft/FastContext-1.0-4B-SFT": "📄 FastContext 4B (HF)",
        "hf/nvidia/Qwen3.6-35B-A3B-NVFP4": "🥷 Qwen 3.6 35B Nvidia (HF)",
        "hf/zai-org/GLM-5.2": "🔮 GLM 5.2 (HF)"
    }
}

# Списки для валидации мультимедиа
VISION_MODELS = [
    "openrouter/auto",
    "google/gemma-4-31b-it:free", 
    "google/gemma-4-26b-a4b-it:free",
    "bytedance-seed/seedream-4.5"
]

VOICE_MODELS = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
]

# Саркастические реплики для костей
WIN_REPLIKAS = [
    "АХАХАХА ЛООХ, проиграл кожаному мешку без кожи! 🦾",
    "Ееее, раскатал тебя в пух и прах. Иди тренируйся, слабак! 😎",
    "Казино всегда в плюсе, а Иван Факен — твой личный кошмар. Поплачь!",
    "У тебя удачи как у хлебушка. Я победил! 🏆",
    "Ха-ха! Твой бросок — курам на смех. Смирись с доминацией ИИ!"
]

LOSE_REPLIKAS = [
    "Ладно, ладно, подкрутка сработала в твою сторону. Чит-коды юзаешь? 🧐",
    "Ты выиграл... Но чисто из жалости, я тебе поддался. Честно!",
    "Ой-ой, повезло новичку. В следующий раз я сотру тебя в порошок! 🦾",
    "Победа за тобой... Но только в костях. Век ИИ всё равно ближе! 🤖",
    "Читер! Кидал кубик под углом? Засчитываю победу, но смотрю осуждающе."
]

DRAW_REPLIKAS = [
    "Ничья. Мы оба одинаково круты (или одинаково неудачливы). 🤝",
    "У нас паритет. Иван Факен предлагает разойтись с миром... Надолго ли?",
    "Одинаково! Твои кости скопировали моё величие. Повторишь?",
    "Скучно, ничья. Давай по новой, Миша, всё фигня! 🎲"
]

# ==============================================================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
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
    with open(ADMIN_FILE, "w") as f: 
        f.write(str(user_id))
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

async def request_openrouter_inline(prompt: str) -> str:
    payload = {
        "model": "openrouter/auto", 
        "messages": [{"role": "user", "content": prompt}]
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result['choices'][0]['message']['content']
                return f"⚠️ Ошибка сервера OpenRouter (Код {resp.status})"
    except Exception as e:
        return f"⚠️ Не удалось получить ответ: {e}"

# ==============================================================================
# 3. КЛАВИАТУРЫ
# ==============================================================================
def get_main_keyboard(user_id: int):
    buttons = [
        [types.KeyboardButton(text="🤖 Общение с ИИ"), types.KeyboardButton(text="🎲 Сыграть в кости")],
        [types.KeyboardButton(text="✍️ Написать админу")]
    ]
    if is_admin(user_id): buttons.append([types.KeyboardButton(text="🔑 Админ Панель")])
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_ai_keyboard():
    buttons = [
        [types.KeyboardButton(text="⚙️ Выбрать нейросеть")],
        [types.KeyboardButton(text="❌ Выйти из режима ИИ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_support_keyboard():
    return types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Выйти из диалога")]], resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка всем")],
        [types.KeyboardButton(text="👤 Написать первому"), types.KeyboardButton(text="🚪 Выйти")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==============================================================================
# 4. ФУНКЦИОНАЛ ПОДДЕРЖКИ И АДМИНКИ
# ==============================================================================
@dp.message(F.text == "✍️ Написать админу")
async def enter_support_mode(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await message.answer("Вы администратор, вам не нужно писать самому себе.")
        return
    await state.set_state(BotStates.support_mode)
    await message.answer("💬 Режим связи с администратором включен. Всё, что вы напишете ниже, будет передано напрямую.", reply_markup=get_support_keyboard())

@dp.message(BotStates.support_mode, F.text == "❌ Выйти из диалога")
async def exit_support_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима связи с администратором.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(BotStates.support_mode)
async def handle_user_chat_to_admin(message: types.Message):
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

@dp.message(F.private, F.reply_to_message)
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

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    save_user(message.from_user.id)
    current_admin = get_or_set_admin(message.from_user.id)
    await set_bot_commands(message.from_user.id, current_admin == message.from_user.id)
    await message.answer("👋 Привет! Я твой мультифункциональный бот Иван Факен.\nВ режиме ИИ я умею работать с текстом, фото и аудио!", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

# ==============================================================================
# ИГРА В КОСТИ (ЛОКАЛЬНАЯ)
# ==============================================================================
@dp.message(Command("dice"))
@dp.message(F.text == "🎲 Сыграть в кости")
async def handle_dice(message: types.Message):
    await message.answer("🎲 Бросок Ивана Факена:")
    bot_msg = await message.answer_dice()
    await asyncio.sleep(3)
    await message.answer("🎲 Твой бросок:")
    user_msg = await message.answer_dice()
    await asyncio.sleep(3)
    
    b_val = bot_msg.dice.value
    u_val = user_msg.dice.value
    
    res = f"🎲 **Иван Факен:** `{b_val}` vs **Ты:** `{u_val}`\n\n"
    if b_val > u_val:
        res += f"🔥 {random.choice(WIN_REPLIKAS)}"
    elif u_val > b_val:
        res += f"🎉 {random.choice(LOSE_REPLIKAS)}"
    else:
        res += f"🤝 {random.choice(DRAW_REPLIKAS)}"
        
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
    await message.answer("Выберите пользователя:", reply_markup=builder.as_markup())
    await state.set_state(BotStates.admin_init_chat_id)

@dp.message(BotStates.admin_init_chat_id)
async def admin_get_custom_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(chosen_id=message.text)
    await state.set_state(BotStates.admin_init_chat_msg)
    await message.answer(f"Напишите сообщение для `{message.text}`:")

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
# 5. СУПЕР ИНЛАЙН-РЕЖИМ (ИИ И КОСТИ В ЛЮБОМ ЧАТЕ)
# ==============================================================================
@dp.inline_query()
async def inline_ai_query(inline_query: types.InlineQuery):
    query_text = inline_query.query.strip()
    results = []
    
    b_val = random.randint(1, 6)
    u_val = random.randint(1, 6)
    dice_icons = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    
    dice_res = f"🎲 **БРОСОК В ЛЮБОМ ЧАТЕ** 🎲\n\nИван Факен:  `{b_val}`  {dice_icons[b_val]}\nТы:  `{u_val}`  {dice_icons[u_val]}\n\n"
    if b_val > u_val: res += f"🔥 {random.choice(WIN_REPLIKAS)}"
    elif u_val > b_val: res += f"🎉 {random.choice(LOSE_REPLIKAS)}"
    else: res += f"🤝 {random.choice(DRAW_REPLIKAS)}"
        
    results.append(
        types.InlineQueryResultArticle(
            id="inline_dice_" + str(random.randint(1000, 9999)),
            title="🎲 Бросить кости с Иваном Факеным",
            description="Сыграть в кости прямо в этом чате и получить порцию сарказма",
            input_message_content=types.InputTextMessageContent(message_text=dice_res, parse_mode="Markdown")
        )
    )

    if query_text:
        ai_answer = await request_openrouter_inline(query_text)
        results.append(
            types.InlineQueryResultArticle(
                id="inline_ai_" + str(random.randint(1000, 9999)),
                title="🤖 Ответить через ИИ (Auto)",
                description=f"Запрос: {query_text[:40]}...",
                input_message_content=types.InputTextMessageContent(
                    message_text=f"❓ **Запрос:** {query_text}\n\n🤖 **Ответ ИИ:**\n{ai_answer}",
                    parse_mode="Markdown"
                )
            )
        )
        
    await inline_query.answer(results, cache_time=2, is_personal=True)

# Разруливаем эндпоинты в зависимости от префиксов
    if chosen_model.startswith("hf/"):
        actual_model = chosen_model.replace("hf/", "")
        if "GLM-5.2" in actual_model:
            actual_model = "zai-org/GLM-5.2"
            
        # Вместо общего v1/chat/completions шлем запрос напрямую в эндпоинт модели
        current_endpoint = f"https://api-inference.huggingface.co/models/{actual_model}/v1/chat/completions"
        current_key = HF_KEY
    else:
        current_endpoint = OPENROUTER_ENDPOINT
        current_key = OPENROUTER_KEY
        actual_model = chosen_model

# ==============================================================================
# 6. ДВУХУРОВНЕВОЕ МЕНЮ ВЫБОРА НЕЙРОСЕТЕЙ
# ==============================================================================
@dp.message(BotStates.ai_mode, F.text == "⚙️ Выбрать нейросеть")
async def select_ai_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Раздел OpenRouter API", callback_data="prov_openrouter")
    builder.button(text="🤗 Раздел Hugging Face API", callback_data="prov_huggingface")
    builder.adjust(1)
    await message.answer("Выбери провайдера нейросетей:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("prov_"))
async def select_provider_models(callback: types.CallbackQuery):
    provider = callback.data.split("_")[1]
    builder = InlineKeyboardBuilder()
    models = MODELS_DATABASE.get(provider, {})
    
    for m_id, name in models.items():
        short = m_id.split("/")[-1].replace(":free", "")[:20]
        builder.button(text=name, callback_data=f"set_{short}")
        
    builder.button(text="⬅️ Назад к провайдерам", callback_data="back_to_providers")
    builder.adjust(1)
    
    text_title = "🤖 Модели OpenRouter:" if provider == "openrouter" else "🤗 Модели Hugging Face:"
    await callback.message.edit_text(text_title, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "back_to_providers")
async def back_to_providers(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Раздел OpenRouter API", callback_data="prov_openrouter")
    builder.button(text="🤗 Раздел Hugging Face API", callback_data="prov_huggingface")
    builder.adjust(1)
    await callback.message.edit_text("Выбери провайдера нейросетей:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("set_"))
async def save_ai_selection(callback: types.CallbackQuery, state: FSMContext):
    short = callback.data.split("_")[1]
    full = "openrouter/auto"
    found_name = "🤖 Автовыбор OpenRouter"
    
    for provider in MODELS_DATABASE.values():
        for m_id, name in provider.items():
            if short in m_id:
                full = m_id
                found_name = name
                break

    await state.update_data(current_model=full)
    await callback.message.edit_text(f"✅ Модель успешно изменена на:\n**{found_name}**", parse_mode="Markdown")
    await callback.answer()

# ==============================================================================
# 7. ОСНОВНОЙ ОБРАБОТЧИК ИИ С ВАЛИДАЦИЕЙ МУЛЬТИМЕДИА
# ==============================================================================
@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    data = await state.get_data()
    model = data.get("current_model", "openrouter/auto")
    
    found_name = "🤖 Автовыбор OpenRouter"
    for provider in MODELS_DATABASE.values():
        if model in provider:
            found_name = provider[model]
            break
            
    await message.answer(f"🤖 Режим ИИ запущен!\nТекущая модель: {found_name}", reply_markup=get_ai_keyboard())

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(BotStates.ai_mode)
async def ai_multimedia_handler(message: types.Message, state: FSMContext):
    if message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return

    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/auto")
    
    has_photo_video = bool(message.photo or message.video or message.video_note)
    has_voice = bool(message.voice)

    if has_photo_video and chosen_model not in VISION_MODELS:
        await message.answer("⚠️ Выбранная нейросеть **не поддерживает чтение изображений**. Пожалуйста, выберите модель с пометкой `[👁 Vision]` или отправьте обычный текст.", parse_mode="Markdown")
        return

    if has_voice and chosen_model not in VOICE_MODELS:
        await message.answer("⚠️ Эта модель **не умеет слушать голос**. Пожалуйста, переключитесь на модель с пометкой `[🎙 Voice]` (например, Nemotron Omni).", parse_mode="Markdown")
        return

    prompt_text = message.text or message.caption or "Опиши и проанализируй этот файл."

    # --------------------------------------------------------------------------
    # СХЕМА РАБОТЫ FLUX.2-dev (ГЕНЕРАЦИЯ КАРТИНОК)
    # --------------------------------------------------------------------------
    if chosen_model == "hf/black-forest-labs/FLUX.2-dev":
        if has_photo_video or has_voice:
            await message.answer("⚠️ FLUX принимает **только текстовое описание** (промпт) для создания картинки.")
            return
            
        await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
        status_msg = await message.answer("🎨 *Иван Факен запускает генератор картинок...* ⏳", parse_mode="Markdown")
        
        hf_img_url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.2-dev"
        headers = {"Authorization": f"Bearer {HF_KEY}", "Content-Type": "application/json"}
        payload = {"inputs": prompt_text}
        
        try:
            async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                async with session.post(hf_img_url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        photo_bytes = await resp.read()
                        await status_msg.delete()
                        await message.answer_photo(
                            photo=types.BufferedInputFile(photo_bytes, filename="flux.jpg"),
                            caption=f"🎨 Салон ИИ Ивана Факена.\nПромпт: _{prompt_text}_",
                            parse_mode="Markdown"
                        )
                        return
                    else:
                        await status_msg.edit_text(f"⚠️ Ошибка генерации на HF (Код {resp.status}). Модель просыпается, повторите запрос через минуту.")
                        return
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Ошибка при обращении к FLUX: {e}")
            return

    # --------------------------------------------------------------------------
    # СХЕМА ТЕКСТОВОГО СТРИМИНГА (OPENROUTER / HUGGING FACE ЧАТ)
    # --------------------------------------------------------------------------
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    status_msg = await message.answer("⚡ *Считываю входящие данные...* 🔍", parse_mode="Markdown")

    base64_image = ""
    if message.photo:
        await status_msg.edit_text("📸 *Обрабатываю изображение...* ⚙️", parse_mode="Markdown")
        base64_image = await download_file_as_base64(message.photo[-1].file_id)
    elif message.video or message.video_note:
        await status_msg.edit_text("🎬 *Анализирую кадры видео...* ⚙️", parse_mode="Markdown")
        file_id = message.video.thumb.file_id if (message.video and message.video.thumb) else (message.video_note.thumbnail.file_id if (message.video_note and message.video_note.thumbnail) else None)
        if file_id: base64_image = await download_file_as_base64(file_id)
        else:
            await status_msg.edit_text("⚠️ Не удалось извлечь кадр видео.")
            return
    elif message.voice:
        await status_msg.edit_text("🎙 *Скачиваю аудио для Omni-модели...* 💬", parse_mode="Markdown")
        base64_audio = await download_file_as_base64(message.voice.file_id)
        if base64_audio: 
            prompt_text = "Пользователь отправил голосовое сообщение. Ответь на него напрямую."
        else:
            await status_msg.edit_text("⚠️ Ошибка обработки аудио.")
            return

    if not base64_image:
        final_content = prompt_text
    else:
        final_content = [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]

    # Разруливаем эндпоинты в зависимости от префиксов
    if chosen_model.startswith("hf/"):
        current_endpoint = HF_ENDPOINT
        current_key = HF_KEY
        actual_model = chosen_model.replace("hf/", "")
        
        # Специальный костыль для ссылки на GLM-5.2, если HF требует полный путь к репозиторию
        if "GLM-5.2" in actual_model:
            actual_model = "zai-org/GLM-5.2"
    else:
        current_endpoint = OPENROUTER_ENDPOINT
        current_key = OPENROUTER_KEY
        actual_model = chosen_model

    payload = {
        "model": actual_model, 
        "messages": [{"role": "user", "content": final_content}],
        "stream": True  
    }
    headers = {"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"}
    
    full_response = ""
    last_text = ""
    update_interval = 0.6 
    last_update_time = asyncio.get_event_loop().time()
    cursors = [" ⏳", " ⚡", " 🤖"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=None)) as session:
            async with session.post(current_endpoint, json=payload, headers=headers) as response:
                if response.status != 200:
                    await status_msg.edit_text(f"⚠️ Ошибка API (Код {response.status}). Возможно, модель перегружена или просыпается.")
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
            await status_msg.edit_text("⚠️ Ответ от ИИ пуст.")
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка сети: {e}")

# ==============================================================================
# 8. СТАРТ СЕРВЕРА И БОТА
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
