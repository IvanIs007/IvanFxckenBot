import asyncio
import logging
import os
import sys
import threading
import random
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1187881528:AAESwXPEf0HhStxCjzOLA0YXzlxzLQM2mH8")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "IvanIsakau").lstrip("@")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Только реально работающие модели
MALFOY_MODELS = [
    "meta-llama/llama-3.2-3b-instruct:free",
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
]

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

greeting_text = "Ух ты, новенький! Обычно люди убегают после первого поста. Ты либо очень смелый, либо очень наивный. В любом случае — добро пожаловать в мой театр абсурда. Я здесь главный актёр. Ты — зритель. Аплодируй, когда я скажу."

forward_map: dict[int, int] = {}
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None
active_chat_users: set[int] = set()
USERS_PER_PAGE = 10

# Кнопки
BTN_START = "👋 Старт"
BTN_CHAT = "🤫 Чат с поддержкой"
BTN_LUCK = "🎲 Кинуть кость"
BTN_BURMALDA = "🎰 Бурмалда"
BTN_MALFOY = "🐍 Малфой"
BTN_STOP = "🛑 Завершить диалог"

MALFOY_SYSTEM_PROMPT = """Ты — Люциус Малфой. Отвечай ТОЛЬКО прямой речью, без описаний действий.
Говори высокомерно, надменно, презрительно к маглам и грязнокровкам.
Чередуй длину ответов: иногда 1-2 предложения, иногда 4-5.
Никогда не используй звёздочки для описания действий. Только прямые цитаты."""

MALFOY_USER_PROMPTS = [
    "Презрительно выскажись о маглах и их образе жизни.",
    "Расскажи о величии и богатстве рода Малфоев.",
    "Дай надменный совет молодому волшебнику о важности чистокровности.",
    "Выскажись о своём влиянии в Министерстве магии.",
    "Сравни чистокровных волшебников с грязнокровками.",
    "Расскажи о воспитании твоего сына Драко.",
    "Поделись философией власти и могущества.",
    "Выскажись о прошлых временах и Тёмном Лорде.",
    "Дай характеристику Хогвартсу и факультету Слизерин.",
    "Расскажи о своём поместье Малфой-мэнор.",
]

@dataclass
class UserInfo:
    chat_id: int
    full_name: str
    username: str | None
    msg_count: int = 0
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)

users: dict[int, UserInfo] = {}
total_messages: int = 0

class AdminStates(StatesGroup):
    waiting_for_greeting = State()

async def is_admin_filter(message: Message) -> bool:
    if ADMIN_ID and message.from_user and message.from_user.id == ADMIN_ID:
        return True
    return bool(message.from_user and message.from_user.username == ADMIN_USERNAME)

async def is_user_filter(message: Message) -> bool:
    return not await is_admin_filter(message)

def user_keyboard():
    """Основная клавиатура - ГЛАВНОЕ ИСПРАВЛЕНИЕ"""
    kb = [
        [KeyboardButton(text=BTN_START)],
        [KeyboardButton(text=BTN_CHAT)],
        [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_BURMALDA)],
        [KeyboardButton(text=BTN_MALFOY)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )

def chat_keyboard():
    """Клавиатура чата"""
    kb = [[KeyboardButton(text=BTN_STOP)]]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Напиши сообщение..."
    )

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="users_p:0"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить приветствие", callback_data="edit_greeting"),
            InlineKeyboardButton(text="👁 Показать приветствие", callback_data="show_greeting"),
        ],
    ])

def users_page_keyboard(page: int, total_pages: int):
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"users_p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"users_p:{page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")],
    ])

async def get_malfoy_response():
    """Получает ответ от нейросети"""
    if not OPENROUTER_API_KEY:
        return random.choice(FALLBACK_QUOTES)

    user_prompt = random.choice(MALFOY_USER_PROMPTS)
    
    for model in MALFOY_MODELS:
        try:
            response = await try_model(model, user_prompt)
            if response and len(response) > 10:
                return response
        except Exception as e:
            logger.warning(f"Модель {model}: {e}")
            continue
    
    return random.choice(FALLBACK_QUOTES)

async def try_model(model, user_prompt):
    """Пробует модель"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": MALFOY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": random.randint(100, 300),
        "temperature": 0.9,
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data["choices"][0]["message"]["content"].strip().replace("*", "")
            raise Exception(f"HTTP {response.status}")

FALLBACK_QUOTES = [
    "Мой отец услышит об этом! Твоя дерзость не останется безнаказанной, уверяю тебя.",
    "Чистота крови — вот что отличает истинных волшебников от грязнокровок. Мой род веками хранил эту традицию, и я не позволю никому её нарушить.",
    "Ты хоть знаешь, с кем разговариваешь? Я — Люциус Малфой. Моё влияние в Министерстве магии простирается дальше, чем твоё воображение.",
    "Мой сын Драко — наследник великого рода. Он вырастет достойным продолжателем дела чистокровных волшебников.",
    "Маглы со своими технологиями... Они даже не представляют, какая сила существует рядом с ними. Жалкие создания.",
    "Малфой-мэнор стоит больше, чем всё имущество твоей семьи за десять поколений. И это лишь малая часть нашего состояния.",
    "Тёмный Лорд понимал истинный порядок вещей. Маги должны править маглами, а не прятаться от них.",
    "Знаешь, что отличает Малфоев от других? Мы не просто говорим о власти — мы её берём. Без колебаний.",
    "Слизерин всегда был оплотом чистокровных волшебников. Хогвартс должен быть благодарен, что такие семьи, как моя, всё ещё посылают туда своих детей.",
]

# =============================================
# ОБРАБОТЧИКИ КОМАНД
# =============================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик /start"""
    if await is_admin_filter(message):
        global admin_chat_id
        admin_chat_id = message.chat.id
        await message.answer(
            f"👋 Админ-панель активна.\nТвой chat ID: <code>{message.chat.id}</code>",
            parse_mode="HTML"
        )
    else:
        # ГЛАВНОЕ ИСПРАВЛЕНИЕ: принудительно показываем клавиатуру
        await message.answer(
            text=greeting_text,
            reply_markup=user_keyboard()
        )

@dp.message(Command("chat"))
async def cmd_chat(message: Message):
    if await is_user_filter(message):
        if message.chat.id in active_chat_users:
            await leave_chat(message)
        else:
            await enter_chat(message)

@dp.message(Command("luck"))
async def cmd_luck(message: Message):
    await message.answer("Бросаю кости...")
    user_dice = await bot.send_dice(message.chat.id, emoji="🎲")
    bot_dice = await bot.send_dice(message.chat.id, emoji="🎲")
    await asyncio.sleep(4)
    u, b = user_dice.dice.value, bot_dice.dice.value
    if u > b: result = "Повезло. Но это случайность."
    elif u < b: result = "Проиграл. Ожидаемо."
    else: result = "Ничья."
    await message.answer(f"Ты: {u} — Я: {b}\n{result}")

@dp.message(Command("burmalda"))
async def cmd_burmalda(message: Message):
    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(3)
    v = msg.dice.value
    if v == 64: text = "Джекпот!"
    elif v > 40: text = "Неплохо."
    else: text = "Пусто."
    await message.answer(text)

@dp.message(Command("malfoy"))
async def cmd_malfoy(message: Message):
    thinking = await message.answer("🐍 *Люциус думает...*", parse_mode="Markdown")
    response = await get_malfoy_response()
    await thinking.delete()
    await message.answer(f"🐍 {response}")

@dp.message(Command("panel"))
async def cmd_panel(message: Message):
    if await is_admin_filter(message):
        await message.answer("⚙️ Панель управления", reply_markup=admin_panel_keyboard())

# =============================================
# ОБРАБОТЧИКИ КНОПОК
# =============================================

@dp.message(F.text == BTN_START)
async def btn_start(message: Message):
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(F.text == BTN_CHAT)
async def btn_chat(message: Message):
    if message.chat.id in active_chat_users:
        await leave_chat(message)
    else:
        await enter_chat(message)

@dp.message(F.text == BTN_STOP)
async def btn_stop(message: Message):
    await leave_chat(message)

@dp.message(F.text == BTN_LUCK)
async def btn_luck(message: Message):
    await cmd_luck(message)

@dp.message(F.text == BTN_BURMALDA)
async def btn_burmalda(message: Message):
    await cmd_burmalda(message)

@dp.message(F.text == BTN_MALFOY)
async def btn_malfoy(message: Message):
    await cmd_malfoy(message)

# =============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================

async def enter_chat(message: Message):
    active_chat_users.add(message.chat.id)
    await message.answer(
        "Приватный чат открыт. Пиши сообщение, оно будет отправлено администратору.",
        reply_markup=chat_keyboard()
    )
    if admin_chat_id:
        user = message.from_user
        await bot.send_message(admin_chat_id, f"🟢 {user.full_name} начал диалог")

async def leave_chat(message: Message):
    active_chat_users.discard(message.chat.id)
    # ВОЗВРАЩАЕМ ОСНОВНУЮ КЛАВИАТУРУ
    await message.answer("Диалог завершён.", reply_markup=user_keyboard())
    if admin_chat_id:
        await bot.send_message(admin_chat_id, f"🔴 {message.from_user.full_name} завершил диалог")

# =============================================
# ОСТАЛЬНЫЕ ОБРАБОТЧИКИ
# =============================================

@dp.message(is_admin_filter, F.reply_to_message)
async def admin_reply(message: Message):
    replied_id = message.reply_to_message.message_id
    user_id = forward_map.get(replied_id)
    if user_id:
        await bot.send_message(user_id, message.text or "Ответ отправлен")
        await message.answer("✅ Отправлено")

@dp.message()
async def handle_any_message(message: Message):
    """Обработчик всех остальных сообщений"""
    if message.text in [BTN_START, BTN_CHAT, BTN_LUCK, BTN_BURMALDA, BTN_MALFOY, BTN_STOP]:
        return
    
    if await is_user_filter(message):
        if message.chat.id in active_chat_users:
            # Пересылаем админу
            if admin_chat_id:
                sent = await bot.send_message(admin_chat_id, f"📨 {message.from_user.full_name}:\n{message.text}")
                forward_map[sent.message_id] = message.chat.id
        else:
            # Если не в чате - показываем клавиатуру
            await message.answer(
                "Используй кнопки меню для навигации.",
                reply_markup=user_keyboard()
            )

# =============================================
# CALLBACKS ДЛЯ АДМИН-ПАНЕЛИ
# =============================================

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    text = f"📊 Статистика\n👥 Пользователей: {len(users)}\n💬 Сообщений: {total_messages}\n🟢 В чате: {len(active_chat_users)}"
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")]
    ]))

@dp.callback_query(F.data == "back_panel")
async def cb_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("⚙️ Панель", reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data == "show_greeting")
async def cb_show(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(f"Приветствие:\n{greeting_text}")

@dp.callback_query(F.data == "edit_greeting")
async def cb_edit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Отправь новый текст приветствия:")
    await state.set_state(AdminStates.waiting_for_greeting)

@dp.message(AdminStates.waiting_for_greeting)
async def save_greeting(message: Message, state: FSMContext):
    global greeting_text
    greeting_text = message.text
    await state.clear()
    await message.answer("✅ Приветствие обновлено!")

# =============================================
# ВЕБ-СЕРВЕР
# =============================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_server():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()

# =============================================
# ЗАПУСК
# =============================================

async def main():
    # Запускаем веб-сервер
    threading.Thread(target=run_server, daemon=True).start()
    
    # Очищаем старые сессии - ВАЖНО ДЛЯ УСТРАНЕНИЯ КОНФЛИКТА
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Устанавливаем команды
    commands = [
        BotCommand(command="start", description="👋 Старт"),
        BotCommand(command="chat", description="🤫 Чат"),
        BotCommand(command="luck", description="🎲 Кость"),
        BotCommand(command="burmalda", description="🎰 Бурмалда"),
        BotCommand(command="malfoy", description="🐍 Малфой"),
    ]
    await bot.set_my_commands(commands)
    
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
