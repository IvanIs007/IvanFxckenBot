import asyncio
import logging
import os
import sys
import threading
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

# Загрузка переменных окружения с fallback-значениями
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1187881528:AAESwXPEf0HhStxCjzOLA0YXzlxzLQM2mH8")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "IvanIsakau").lstrip("@")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

logger.info(f"🔑 BOT_TOKEN: {BOT_TOKEN[:15]}...")
logger.info(f"👑 ADMIN: @{ADMIN_USERNAME}")
logger.info(f"🌐 PORT: {PORT}")
logger.info(f"🤖 OpenRouter API: {'✅' if OPENROUTER_API_KEY else '❌ (не задан)'}")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

greeting_text: str = "Ух ты, новенький! Обычно люди убегают после первого поста. Ты либо очень смелый, либо очень наивный. В любом случае — добро пожаловать в мой театр абсурда. Я здесь главный актёр. Ты — зритель. Аплодируй, когда я скажу."
forward_map: dict[int, int] = {}
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None
active_chat_users: set[int] = set()

USERS_PER_PAGE = 10

BTN_CHAT      = "🤫Приватный диалог"
BTN_STOP      = "🛑 Завершить диалог"
BTN_LUCK      = "🎲 Кинуть кость"
BTN_BURMALDA  = "Бурмалда 🎰"
BTN_START     = "👋 Старт"
BTN_MALFOY    = "Малфой 🐍"

MALFOY_PROMPT = """Ты — Люциус Малфой, чистокровный волшебник, аристократ, бывший Пожиратель Смерти. 
Ты высокомерен, надменен, презираешь маглов и полукровок. 
Ты говоришь изысканно, но язвительно. Ты всегда напоминаешь о чистоте крови и величии рода Малфоев.
Выдай случайную фразу в стиле Люциуса Малфоя: это может быть цитата, насмешка, напутствие или философское высказывание.
Ответ должен быть на русском языке, от 1 до 3 предложений. Только прямая речь, без описаний."""

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

def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CHAT)],
            [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_BURMALDA)],
            [KeyboardButton(text=BTN_MALFOY)],
            [KeyboardButton(text=BTN_START)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие...",
    )

def chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STOP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши сообщение поддержке...",
    )

def admin_panel_keyboard() -> InlineKeyboardMarkup:
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

def users_page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
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

async def get_malfoy_response() -> str:
    if not OPENROUTER_API_KEY:
        import random
        fallback_quotes = [
            "Мой отец услышит об этом!",
            "Чистота крови — вот что отличает нас от этих... маглов.",
            "Ты хотя бы знаешь, с кем разговариваешь? Я — Люциус Малфой.",
            "В этом мире есть вещи похуже смерти. Например, позор для семьи.",
        ]
        return random.choice(fallback_quotes)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/malfoy_bot",
        "X-Title": "MalfoyBot",
    }
    
    payload = {
        "model": "meta-llama/llama-3.2-3b-instruct:free",
        "messages": [
            {"role": "system", "content": MALFOY_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в своём стиле, Люциус."}
        ],
        "max_tokens": 150,
        "temperature": 0.9,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    logger.error(f"OpenRouter API error: {response.status}")
                    return "Очевидно, даже нейросети боятся меня. Попробуйте позже."
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return "Что-то пошло не так. Даже магия Малфоев иногда даёт сбой."

@dp.message(CommandStart(), is_admin_filter)
async def cmd_start_admin(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await setup_commands()
    await message.answer(
        f"👋 Админ-панель активна.\n"
        f"Твой chat ID: <code>{message.chat.id}</code>\n\n"
        "Сообщения пользователей приходят, когда они активируют режим поддержки. "
        "Отвечай реплаем на сообщение — ответ уйдёт пользователю.\n\n"
        "Используй /panel для управления ботом.",
        parse_mode="HTML",
    )

@dp.message(CommandStart(), is_user_filter)
async def cmd_start_user(message: Message) -> None:
    await message.answer(greeting_text, reply_markup=user_keyboard())

async def enter_chat(message: Message) -> None:
    active_chat_users.add(message.chat.id)
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

async def leave_chat(message: Message) -> None:
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

@dp.message(Command("chat"), is_user_filter)
async def cmd_chat(message: Message) -> None:
    if message.chat.id in active_chat_users:
        await leave_chat(message)
    else:
        await enter_chat(message)

@dp.message(is_user_filter, F.text == BTN_CHAT)
async def btn_enter_chat(message: Message) -> None:
    await enter_chat(message)

@dp.message(is_user_filter, F.text == BTN_STOP)
async def btn_leave_chat(message: Message) -> None:
    await leave_chat(message)

@dp.message(Command("panel"), is_admin_filter)
async def cmd_panel(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await message.answer(
        "⚙️ <b>Панель управления</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
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
            f"🟢 В чате сейчас: <b>{len(active_chat_users)}</b>\n"
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
async def cb_users_page(callback: CallbackQuery) -> None:
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
            status = "🟢" if u.chat_id in active_chat_users else "⚫️"
            lines.append(
                f"{status} <b>{u.full_name}</b> {uname}\n"
                f"  💬 {u.msg_count} сообщ. | 🕐 {u.last_seen.strftime('%d.%m %H:%M')}"
            )
        text = f"👥 <b>Пользователи</b>\n\n" + "\n\n".join(lines)
        markup = users_page_keyboard(page, total_pages)

    await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data == "back_panel")
async def cb_back_panel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "⚙️ <b>Панель управления</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()

@dp.callback_query(F.data == "show_greeting")
async def cb_show_greeting(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        f"📝 <b>Текущее приветствие:</b>\n\n{greeting_text}",
        parse_mode="HTML",
    )

@dp.callback_query(F.data == "edit_greeting")
async def cb_edit_greeting(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "✏️ Отправь новый текст приветствия.\n"
        "Пользователи увидят его при команде /start.\n\n"
        "/cancel — отмена",
    )
    await state.set_state(AdminStates.waiting_for_greeting)

@dp.message(Command("cancel"), AdminStates.waiting_for_greeting)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=admin_panel_keyboard())

@dp.message(AdminStates.waiting_for_greeting)
async def receive_new_greeting(message: Message, state: FSMContext) -> None:
    global greeting_text
    greeting_text = message.text or greeting_text
    await state.clear()
    await message.answer(
        f"✅ Приветствие обновлено!\n\n<b>Новое приветствие:</b>\n{greeting_text}",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

@dp.message(is_admin_filter, F.reply_to_message)
async def handle_admin_reply(message: Message) -> None:
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

def track_user(message: Message) -> None:
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

async def forward_to_admin(message: Message) -> None:
    if admin_chat_id is None:
        logger.warning("Admin chat ID не задан.")
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

@dp.message(is_user_filter, F.text == BTN_START)
async def btn_start(message: Message) -> None:
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(is_user_filter, F.text == BTN_LUCK)
async def btn_luck(message: Message) -> None:
    await cmd_luck(message)

@dp.message(Command("luck"))
async def cmd_luck(message: Message) -> None:
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
        await message.answer(f"Ошибка: {e}")

@dp.message(is_user_filter, F.text == BTN_BURMALDA)
async def btn_burmalda(message: Message) -> None:
    await cmd_burmalda(message)

@dp.message(Command("burmalda"))
async def cmd_burmalda(message: Message) -> None:
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
        await message.answer(f"Ошибка: {e}")

@dp.message(is_user_filter, F.text == BTN_MALFOY)
async def btn_malfoy(message: Message) -> None:
    await cmd_malfoy(message)

@dp.message(Command("malfoy"))
async def cmd_malfoy(message: Message) -> None:
    thinking_msg = await message.answer("🐍 *Люциус Малфой поправляет мантию и задумчиво смотрит на тебя...*", parse_mode="Markdown")
    malfoy_response = await get_malfoy_response()
    await thinking_msg.delete()
    await message.answer(f"🐍 {malfoy_response}")

@dp.message(is_user_filter, F.text.startswith("/"))
async def handle_unknown_command(message: Message) -> None:
    await message.answer(
        "Ты серьёзно ошибся в команде? Я ожидал большего. Ну ладно. "
        "Вот тебе список того, что я умею. Не благодари.\n\n"
        "/start — начать диалог\n"
        f"/chat — {BTN_CHAT}\n"
        "/luck — кинуть кость\n"
        "/burmalda — Бурмалда 🎰\n"
        "/malfoy — спросить Люциуса Малфоя 🐍"
    )

@dp.message(is_user_filter)
async def handle_user_message(message: Message) -> None:
    if message.text in [BTN_CHAT, BTN_STOP, BTN_LUCK, BTN_BURMALDA, BTN_START, BTN_MALFOY]:
        return
        
    if message.chat.id not in active_chat_users:
        return
    track_user(message)
    await forward_to_admin(message)

# ──────────────────────────────────────────────
# Веб-сервер для Render (Health Check)
# ──────────────────────────────────────────────

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        # Красивая HTML-страница для проверки
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Malfoy Bot - Status</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #1a472a, #2d5a3f);
                    color: white;
                }
                .container {
                    text-align: center;
                    padding: 40px;
                    background: rgba(0,0,0,0.3);
                    border-radius: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
                }
                h1 { font-size: 3em; margin: 0; }
                .status { color: #4CAF50; font-size: 1.5em; margin: 20px 0; }
                .snake { font-size: 4em; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="snake">🐍</div>
                <h1>Malfoy Bot</h1>
                <div class="status">✅ Работает</div>
                <p>Люциус Малфой следит за порядком...</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # Отключаем логи HTTP-запросов
        return

def run_web_server():
    """Запускает веб-сервер для Render Health Check"""
    try:
        server_address = ("0.0.0.0", PORT)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"🌐 Веб-сервер запущен на порту {PORT}")
        logger.info(f"📋 Health Check URL: http://0.0.0.0:{PORT}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"❌ Ошибка запуска веб-сервера: {e}")

# ──────────────────────────────────────────────
# Запуск бота
# ──────────────────────────────────────────────

async def setup_commands() -> None:
    user_commands = [
        BotCommand(command="start",     description="👋 Начать диалог"),
        BotCommand(command="chat",      description=f"{BTN_CHAT}"),
        BotCommand(command="luck",      description="🎲 Кинуть кость"),
        BotCommand(command="burmalda",  description="🎰 Бурмалда"),
        BotCommand(command="malfoy",    description="🐍 Спросить Люциуса Малфоя"),
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

async def main() -> None:
    logger.info("🚀 Запуск Malfoy Bot...")
    
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("💓 Health-check сервер запущен")
    
    # Удаляем старые вебхуки и сбрасываем обновления
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🔄 Вебхуки очищены")
    
    # Настраиваем команды бота
    await setup_commands()
    logger.info("⚙️ Команды настроены")
    
    # Запускаем поллинг
    logger.info("🤖 Бот запущен и готов к работе!")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
        sys.exit(1)
