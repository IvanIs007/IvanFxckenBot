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
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

greeting_text = "Ух ты, новенький! Обычно люди убегают после первого поста. Ты либо очень смелый, либо очень наивный. В любом случае — добро пожаловать в мой театр абсурда. Я здесь главный актёр. Ты — зритель. Аплодируй, когда я скажу."

forward_map: dict[int, int] = {}
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None
active_chat_users: set[int] = set()
malfoy_chat_users: set[int] = set()  # Пользователи в диалоге с Малфоем
USERS_PER_PAGE = 10

# Кнопки
BTN_START = "👋 Старт"
BTN_CHAT = "🤫 Чат с поддержкой"
BTN_LUCK = "🎲 Кинуть кость"
BTN_BURMALDA = "🎰 Бурмалда"
BTN_MALFOY = "🐍 Малфой"
BTN_MALFOY_CHAT = "💬 Диалог с Малфоем"
BTN_STOP = "🛑 Завершить диалог"
BTN_STOP_MALFOY = "🚪 Покинуть Малфоя"

MALFOY_SYSTEM_PROMPT = """Ты — Люциус Малфой, чистокровный волшебник, аристократ, бывший Пожиратель Смерти. 
Ты высокомерен, надменен, презираешь маглов и полукровок. 
Ты говоришь изысканно, но язвительно. Ты всегда напоминаешь о чистоте крови и величии рода Малфоев.
Отвечай в стиле Люциуса Малфоя: надменно, презрительно, но изысканно.
Не используй звёздочки для описания действий. Только прямая речь.
Можешь использовать обращения: "магл", "грязнокровка", "жалкий человек".
Иногда упоминай своего сына Драко, поместье Малфой-мэнор, Министерство магии, Тёмного Лорда."""

MALFOY_RANDOM_PROMPTS = [
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

# История диалогов с Малфоем
malfoy_history: dict[int, list[dict]] = {}

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

class MalfoyStates(StatesGroup):
    chatting = State()

async def is_admin_filter(message: Message) -> bool:
    if ADMIN_ID and message.from_user and message.from_user.id == ADMIN_ID:
        return True
    return bool(message.from_user and message.from_user.username == ADMIN_USERNAME)

async def is_user_filter(message: Message) -> bool:
    return not await is_admin_filter(message)

def user_keyboard():
    kb = [
        [KeyboardButton(text=BTN_START)],
        [KeyboardButton(text=BTN_CHAT)],
        [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_BURMALDA)],
        [KeyboardButton(text=BTN_MALFOY), KeyboardButton(text=BTN_MALFOY_CHAT)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )

def chat_keyboard():
    kb = [[KeyboardButton(text=BTN_STOP)]]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Напиши сообщение..."
    )

def malfoy_chat_keyboard():
    kb = [[KeyboardButton(text=BTN_STOP_MALFOY)]]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Напиши Малфою..."
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

async def call_deepseek(messages: list[dict]) -> str:
    """Вызов DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        return random.choice(FALLBACK_QUOTES)

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.9,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip().replace("*", "")
                else:
                    logger.error(f"DeepSeek API error: {response.status}")
                    return random.choice(FALLBACK_QUOTES)
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return random.choice(FALLBACK_QUOTES)

async def get_malfoy_response() -> str:
    """Случайная фраза Малфоя"""
    messages = [
        {"role": "system", "content": MALFOY_SYSTEM_PROMPT},
        {"role": "user", "content": random.choice(MALFOY_RANDOM_PROMPTS)}
    ]
    return await call_deepseek(messages)

async def get_malfoy_chat_response(user_id: int, user_message: str) -> str:
    """Ответ Малфоя в диалоге"""
    # Инициализируем историю если нужно
    if user_id not in malfoy_history:
        malfoy_history[user_id] = [
            {"role": "system", "content": MALFOY_SYSTEM_PROMPT}
        ]
    
    # Добавляем сообщение пользователя
    malfoy_history[user_id].append({"role": "user", "content": user_message})
    
    # Ограничиваем историю 10 последними сообщениями
    if len(malfoy_history[user_id]) > 11:  # system + 10 сообщений
        malfoy_history[user_id] = [malfoy_history[user_id][0]] + malfoy_history[user_id][-10:]
    
    # Получаем ответ
    response = await call_deepseek(malfoy_history[user_id])
    
    # Добавляем ответ в историю
    malfoy_history[user_id].append({"role": "assistant", "content": response})
    
    return response

FALLBACK_QUOTES = [
    "Мой отец услышит об этом! Твоя дерзость не останется безнаказанной, уверяю тебя.",
    "Чистота крови — вот что отличает истинных волшебников от грязнокровок. Мой род веками хранил эту традицию, и я не позволю никому её нарушить.",
    "Ты хоть знаешь, с кем разговариваешь? Я — Люциус Малфой. Моё влияние в Министерстве магии простирается дальше, чем твоё воображение.",
    "Мой сын Драко — наследник великого рода. Он вырастет достойным продолжателем дела чистокровных волшебников.",
    "Маглы со своими технологиями... Они даже не представляют, какая сила существует рядом с ними. Жалкие создания.",
    "Малфой-мэнор стоит больше, чем всё имущество твоей семьи за десять поколений. И это лишь малая часть нашего состояния.",
    "Тёмный Лорд понимал истинный порядок вещей. Маги должны править маглами, а не прятаться от них.",
]

# =============================================
# ОБРАБОТЧИКИ КОМАНД
# =============================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if await is_admin_filter(message):
        global admin_chat_id
        admin_chat_id = message.chat.id
        await message.answer(
            f"👋 Админ-панель активна.\nТвой chat ID: <code>{message.chat.id}</code>",
            parse_mode="HTML"
        )
    else:
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
    try:
        await message.answer(
            "Ты действительно хочешь рискнуть? Против меня? Это не риск. Это самоубийство. "
            "Но я люблю зрителей. Especially тех, кто проигрывает красиво. "
            "Давай. Покажи мне, как ты падаешь."
        )
        user_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        bot_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        await asyncio.sleep(4)
        u = user_dice.dice.value
        b = bot_dice.dice.value
        if u > b:
            result = (
                "Что? Ты выиграл? Случайность. Чистая случайность. Не привыкай. "
                "Это не повторится. Даже если будешь играть до конца жизни. "
                "И знаешь что? Я дам тебе реванш. Из чистого любопытства. "
                "Посмотрим, повезёт ли тебе дважды."
            )
        elif u < b:
            result = (
                "И что я говорил? Ты проиграл. Как и ожидалось. "
                "Не расстраивайся. Ты не первый. Ты не последний. "
                "Ты просто очередной, кто попытался бросить вызов Малфою и пожалел об этом."
            )
        else:
            result = (
                "Ничья? Неожиданно. У тебя есть удача. Или я просто отвлёкся. "
                "Давай переиграем. Мне не нравится оставлять дела незаконченными. "
                "Тем более — когда они такие близкие к моей победе."
            )
        await message.answer(f"Ты: {u} — Я: {b}\n{result}")
    except Exception as e:
        logger.error(f"/luck error: {e}")

@dp.message(Command("burmalda"))
async def cmd_burmalda(message: Message):
    try:
        await message.answer(
            "Так-так, казино... И всё благодаря Макдональд. Она, видимо, решила, что мне не хватает развлечений. "
            "Что ж, раз уж ты тут — давай проверим, есть ли у тебя что-то кроме наглости."
        )
        msg = await message.answer_dice(emoji="🎰")
        await asyncio.sleep(3)
        value = msg.dice.value
        if value == 64:
            text = "Джекпот! Ты сорвал куш, хотя я сомневаюсь, что это поможет тебе в жизни."
        elif value > 40:
            text = "Неплохо. Почти что-то достойное. Но до моего величия тебе далеко."
        else:
            text = "Пусто. Как и в твоих карманах. Типичный результат для такого игрока."
        await message.answer(text)
    except Exception as e:
        logger.error(f"/burmalda error: {e}")

@dp.message(Command("malfoy"))
async def cmd_malfoy(message: Message):
    thinking = await message.answer("🐍 *Люциус Малфой поправляет мантию и задумчиво смотрит на тебя...*", parse_mode="Markdown")
    response = await get_malfoy_response()
    await thinking.delete()
    await message.answer(f"🐍 {response}")

@dp.message(Command("malfoy_chat"))
async def cmd_malfoy_chat(message: Message):
    """Начать диалог с Малфоем"""
    if message.chat.id in malfoy_chat_users:
        await leave_malfoy_chat(message)
    else:
        await enter_malfoy_chat(message)

@dp.message(Command("panel"))
async def cmd_panel(message: Message):
    if await is_admin_filter(message):
        global admin_chat_id
        admin_chat_id = message.chat.id
        await message.answer("⚙️ Панель управления", reply_markup=admin_panel_keyboard())

# =============================================
# ОБРАБОТЧИКИ КНОПОК
# =============================================

@dp.message(F.text == BTN_START)
async def btn_start(message: Message):
    # Выходим из всех чатов
    active_chat_users.discard(message.chat.id)
    malfoy_chat_users.discard(message.chat.id)
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(F.text == BTN_CHAT)
async def btn_chat(message: Message):
    if message.chat.id in malfoy_chat_users:
        await leave_malfoy_chat(message)
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

@dp.message(F.text == BTN_MALFOY_CHAT)
async def btn_malfoy_chat(message: Message):
    if message.chat.id in malfoy_chat_users:
        await leave_malfoy_chat(message)
    else:
        await enter_malfoy_chat(message)

@dp.message(F.text == BTN_STOP_MALFOY)
async def btn_stop_malfoy(message: Message):
    await leave_malfoy_chat(message)

# =============================================
# ДИАЛОГ С МАЛФОЕМ
# =============================================

async def enter_malfoy_chat(message: Message):
    """Вход в диалог с Малфоем"""
    malfoy_chat_users.add(message.chat.id)
    active_chat_users.discard(message.chat.id)  # Выходим из чата поддержки
    
    # Очищаем историю
    malfoy_history[message.chat.id] = [
        {"role": "system", "content": MALFOY_SYSTEM_PROMPT}
    ]
    
    await message.answer(
        "🐍 *Люциус Малфой обратил на тебя внимание...*\n\n"
        "*Он смотрит на тебя с презрением, но, кажется, готов выслушать.*\n\n"
        "Что скажешь ему?",
        parse_mode="Markdown",
        reply_markup=malfoy_chat_keyboard()
    )

async def leave_malfoy_chat(message: Message):
    """Выход из диалога с Малфоем"""
    malfoy_chat_users.discard(message.chat.id)
    if message.chat.id in malfoy_history:
        del malfoy_history[message.chat.id]
    
    await message.answer(
        "🐍 *Малфой презрительно фыркнул и отвернулся.*\n"
        "Диалог с Люциусом Малфоем завершён.",
        parse_mode="Markdown",
        reply_markup=user_keyboard()
    )

# =============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================

async def enter_chat(message: Message):
    active_chat_users.add(message.chat.id)
    malfoy_chat_users.discard(message.chat.id)  # Выходим из чата с Малфоем
    
    await message.answer(
        "О, приватный чат. Ты либо очень смелый, либо очень отчаянный. "
        "В любом случае — я впечатлён твоей наглостью. Спрашивай. "
        "Но не жалуйся потом, что не предупредил.",
        reply_markup=chat_keyboard()
    )
    if admin_chat_id:
        user = message.from_user
        uname = f"@{user.username}" if user.username else "(без username)"
        await bot.send_message(
            admin_chat_id,
            f"🟢 <b>{user.full_name}</b> {uname} начал диалог — отвечай реплаем.",
            parse_mode="HTML",
        )

async def leave_chat(message: Message):
    active_chat_users.discard(message.chat.id)
    await message.answer("Диалог завершен.", reply_markup=user_keyboard())
    if admin_chat_id:
        user = message.from_user
        uname = f"@{user.username}" if user.username else "(без username)"
        await bot.send_message(
            admin_chat_id,
            f"🔴 <b>{user.full_name}</b> {uname} завершил диалог.",
            parse_mode="HTML",
        )

def track_user(message: Message):
    global total_messages
    user = message.from_user
    if not user:
        return
    now = datetime.now()
    if user.id not in users:
        users[user.id] = UserInfo(
            chat_id=message.chat.id,
            full_name=user.full_name,
            username=user.username,
            first_seen=now,
            last_seen=now,
        )
    users[user.id].msg_count += 1
    users[user.id].last_seen = now
    users[user.id].full_name = user.full_name
    users[user.id].username = user.username
    total_messages += 1

async def forward_to_admin(message: Message):
    if admin_chat_id is None:
        return

    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(без username)"

    reply_context = ""
    if message.reply_to_message:
        quoted = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or "(медиа)"
        )
        reply_context = f"↩️ <i>В ответ на:</i> «{quoted[:100]}»\n\n"

    header = (
        f"📨 <b>{user.full_name}</b> {username_part}\n"
        f"ID: <code>{user.id}</code>\n\n"
        f"{reply_context}"
    )

    try:
        if message.text:
            sent = await bot.send_message(chat_id=admin_chat_id, text=header + message.text, parse_mode="HTML")
        elif message.photo:
            sent = await bot.send_photo(chat_id=admin_chat_id, photo=message.photo[-1].file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.document:
            sent = await bot.send_document(chat_id=admin_chat_id, document=message.document.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.voice:
            sent = await bot.send_voice(chat_id=admin_chat_id, voice=message.voice.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.sticker:
            await bot.send_message(chat_id=admin_chat_id, text=header + f"[Стикер: {message.sticker.emoji or ''}]", parse_mode="HTML")
            sent = await bot.send_sticker(chat_id=admin_chat_id, sticker=message.sticker.file_id)
        else:
            sent = await bot.send_message(chat_id=admin_chat_id, text=header + "[Неподдерживаемый тип сообщения]", parse_mode="HTML")

        forward_map[sent.message_id] = message.chat.id

    except Exception as e:
        logger.error(f"Failed to forward message: {e}")

# =============================================
# ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ
# =============================================

@dp.message(is_admin_filter, F.reply_to_message)
async def handle_admin_reply(message: Message):
    replied_id = message.reply_to_message.message_id
    user_chat_id = forward_map.get(replied_id)

    if user_chat_id is None:
        await message.answer("⚠️ Не удалось найти пользователя для этого сообщения.")
        return

    try:
        kb = chat_keyboard() if user_chat_id in active_chat_users else ReplyKeyboardRemove()
        if message.text:
            await bot.send_message(chat_id=user_chat_id, text=message.text, reply_markup=kb)
        elif message.photo:
            await bot.send_photo(chat_id=user_chat_id, photo=message.photo[-1].file_id, caption=message.caption, reply_markup=kb)
        elif message.document:
            await bot.send_document(chat_id=user_chat_id, document=message.document.file_id, caption=message.caption, reply_markup=kb)
        elif message.voice:
            await bot.send_voice(chat_id=user_chat_id, voice=message.voice.file_id, caption=message.caption, reply_markup=kb)
        else:
            await message.answer("Данный тип медиа пока не поддерживается для отправки ответа.")
            return
        await message.answer("✅ Ответ отправлен.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")

# =============================================
# CALLBACKS ДЛЯ АДМИН-ПАНЕЛИ
# =============================================

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    total_users = len(users)
    if total_users == 0:
        text = "📊 <b>Статистика</b>\n\nПока нет ни одного пользователя."
    else:
        top = sorted(users.values(), key=lambda u: u.msg_count, reverse=True)[:5]
        top_lines = "\n".join(
            f"  {i+1}. {u.full_name} — {u.msg_count} сообщ."
            for i, u in enumerate(top)
        )
        last_active = max(users.values(), key=lambda u: u.last_seen)
        text = (
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{total_users}</b>\n"
            f"💬 Сообщений всего: <b>{total_messages}</b>\n"
            f"🟢 В чате поддержки: <b>{len(active_chat_users)}</b>\n"
            f"🐍 В диалоге с Малфоем: <b>{len(malfoy_chat_users)}</b>\n"
            f"🕐 Последний активный: <b>{last_active.full_name}</b> "
            f"({last_active.last_seen.strftime('%d.%m %H:%M')})\n\n"
            f"🏆 <b>Топ по сообщениям:</b>\n{top_lines}"
        )
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")]
        ]),
    )

@dp.callback_query(F.data.startswith("users_p:"))
async def cb_users_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[1])
    sorted_users = sorted(users.values(), key=lambda u: u.last_seen, reverse=True)
    total_pages = max(1, (len(sorted_users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = sorted_users[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]

    if not chunk:
        text = "👥 <b>Пользователи</b>\n\nПока нет ни одного пользователя."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")]
        ])
    else:
        lines = []
        for u in chunk:
            uname = f"@{u.username}" if u.username else "(без username)"
            status = "🟢" if u.chat_id in active_chat_users else "🐍" if u.chat_id in malfoy_chat_users else "⚫️"
            lines.append(
                f"{status} <b>{u.full_name}</b> {uname}\n"
                f"  💬 {u.msg_count} сообщ. | 🕐 {u.last_seen.strftime('%d.%m %H:%M')}"
            )
        text = f"👥 <b>Пользователи</b>\n\n" + "\n\n".join(lines)
        markup = users_page_keyboard(page, total_pages)

    await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data == "back_panel")
async def cb_back_panel(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "⚙️ <b>Панель управления</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "show_greeting")
async def cb_show_greeting(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        f"📝 <b>Текущее приветствие:</b>\n\n{greeting_text}",
        parse_mode="HTML",
    )

@dp.callback_query(F.data == "edit_greeting")
async def cb_edit_greeting(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "✏️ Отправь новый текст приветствия.\n"
        "Пользователи увидят его при команде /start.\n\n"
        "/cancel — отмена",
    )
    await state.set_state(AdminStates.waiting_for_greeting)

@dp.message(Command("cancel"), AdminStates.waiting_for_greeting)
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=admin_panel_keyboard())

@dp.message(AdminStates.waiting_for_greeting)
async def receive_new_greeting(message: Message, state: FSMContext):
    global greeting_text
    greeting_text = message.text or greeting_text
    await state.clear()
    await message.answer(
        f"✅ Приветствие обновлено!\n\n<b>Новое приветствие:</b>\n{greeting_text}",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

# =============================================
# ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ
# =============================================

@dp.message()
async def handle_any_message(message: Message):
    # Игнорируем кнопки
    if message.text in [BTN_START, BTN_CHAT, BTN_LUCK, BTN_BURMALDA, BTN_MALFOY, BTN_MALFOY_CHAT, BTN_STOP, BTN_STOP_MALFOY]:
        return
    
    if await is_admin_filter(message):
        return
    
    # Если пользователь в диалоге с Малфоем
    if message.chat.id in malfoy_chat_users:
        track_user(message)
        thinking = await message.answer("🐍 *Малфой задумался...*", parse_mode="Markdown")
        response = await get_malfoy_chat_response(message.chat.id, message.text)
        await thinking.delete()
        await message.answer(f"🐍 {response}", reply_markup=malfoy_chat_keyboard())
        return
    
    # Если пользователь в чате поддержки
    if message.chat.id in active_chat_users:
        track_user(message)
        await forward_to_admin(message)
        return
    
    # Если нигде - показываем меню
    await message.answer(
        "Используй кнопки меню для навигации.",
        reply_markup=user_keyboard()
    )

# =============================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER
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
# ЗАПУСК БОТА
# =============================================

async def setup_commands():
    user_commands = [
        BotCommand(command="start", description="👋 Старт"),
        BotCommand(command="chat", description="🤫 Чат с поддержкой"),
        BotCommand(command="luck", description="🎲 Кинуть кость"),
        BotCommand(command="burmalda", description="🎰 Бурмалда"),
        BotCommand(command="malfoy", description="🐍 Случайная фраза Малфоя"),
        BotCommand(command="malfoy_chat", description="💬 Диалог с Малфоем"),
    ]
    admin_commands = user_commands + [
        BotCommand(command="panel", description="⚙️ Панель управления"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    if admin_chat_id:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_chat_id))
        except Exception:
            pass

async def main():
    logger.info("🚀 Запуск Malfoy Bot с DeepSeek API...")
    
    threading.Thread(target=run_server, daemon=True).start()
    logger.info(f"💓 Веб-сервер на порту {PORT}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🔄 Сессии очищены")
    
    await setup_commands()
    logger.info("✅ Бот запущен!")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
