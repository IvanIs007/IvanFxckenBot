import asyncio
import logging
import os
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "mr_zefirka").lstrip("@")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

greeting_text: str = "✌️ Здарова! Я новый бот. Можешь чекнуть мои треки, прыгнуть в приватный чат или рискнуть сыграть со мной в кости."
forward_map: dict[int, int] = {}
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None
active_chat_users: set[int] = set()

USERS_PER_PAGE = 10

BTN_CHAT    = "🤫Приватный диалог"
BTN_TRACKS  = "🎵 Треки IvanFucken"
BTN_STOP    = "🛑 Завершить диалог"
BTN_LUCK    = "🎲 Кинуть кость"
BTN_START   = "👋 Старт"

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

# Функция-фильтр для проверки на админа
async def is_admin_filter(message: Message) -> bool:
    if ADMIN_ID and message.from_user and message.from_user.id == ADMIN_ID:
        return True
    return bool(message.from_user and message.from_user.username == ADMIN_USERNAME)

# Функция-фильтр для проверки на обычного пользователя
async def is_user_filter(message: Message) -> bool:
    return not await is_admin_filter(message)

# ──────────────────────────────────────────────
# Клавиатуры
# ──────────────────────────────────────────────

def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CHAT)],
            [KeyboardButton(text=BTN_TRACKS)],
            [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_START)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбирай, че делать будем...",
    )

def chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STOP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Пиши сюда, админ прочитает...",
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

# ──────────────────────────────────────────────
# Хэндлеры команд
# ──────────────────────────────────────────────

@dp.message(CommandStart(), is_admin_filter)
async def cmd_start_admin(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await setup_commands()
    await message.answer(
        f"👋 Здарова, босс! Твоя админка готова.\n"
        f"Твой chat ID: <code>{message.chat.id}</code>\n\n"
        "Когда юзеры пишут в приватный чат, сообщения летят сюда. Отвечай реплаем.\n"
        "Команда /panel откроет настройки логов.",
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
            f"🟢 <b>{user.full_name}</b> {uname} залез в приватный чат — отвечай реплаем.",
            parse_mode="HTML",
        )

async def leave_chat(message: Message) -> None:
    active_chat_users.discard(message.chat.id)
    await message.answer("Диалог завершен. Свободен!", reply_markup=user_keyboard())
    if admin_chat_id:
        user = message.from_user
        uname = f"@{user.username}" if user.username else "(без username)"
        await bot.send_message(
            admin_chat_id,
            f"🔴 <b>{user.full_name}</b> {uname} вышел из чата.",
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

# Хэндлеры для треков
async def show_tracks(message: Message) -> None:
    tracks_list = (
        "🔥 <b>Список треков IvanFucken:</b>\n\n"
        "1. Заводной Поллинг (Hardstyle Mix)\n"
        "2. Порт 10000 и одна ночь\n"
        "3. Логи на Максимум (Hyperpop Edit)\n"
        "4. Веб-Сервер в огне\n"
        "5. Кубики Судьбы (Happy Hardcore)\n\n"
        "ℹ️ <i>(Тут ты можешь вписать реальные названия своих любимых треков!)</i>"
    )
    await message.answer(tracks_list, parse_mode="HTML")

@dp.message(Command("tracks"), is_user_filter)
async def cmd_tracks(message: Message) -> None:
    await show_tracks(message)

@dp.message(is_user_filter, F.text == BTN_TRACKS)
async def btn_tracks(message: Message) -> None:
    await show_tracks(message)

@dp.message(Command("panel"), is_admin_filter)
async def cmd_panel(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await message.answer(
        "⚙️ <b>Панель управления</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

# ──────────────────────────────────────────────
# Коллбэки админ-панели
# ──────────────────────────────────────────────

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    total_users = len(users)
    if total_users == 0:
        text = "📊 <b>Статистика</b>\n\nПока пусто."
    else:
        top = sorted(users.values(), key=lambda u: u.msg_count, reverse=True)[:5]
        top_lines = "\n".join(
            f"  {i+1}. {u.full_name} — {u.msg_count} сообщ."
            for i, u in enumerate(top)
        )
        last_active = max(users.values(), key=lambda u: u.last_seen)
        text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Уникальных юзеров: <b>{total_users}</b>\n"
            f"💬 Всего сообщений: <b>{total_messages}</b>\n"
            f"🟢 В чатах прямо сейчас: <b>{len(active_chat_users)}</b>\n"
            f"🕐 Последний активный: <b>{last_active.full_name}</b> "
            f"({last_active.last_seen.strftime('%d.%m %H:%M')})\n\n"
            f"🏆 <b>Топ флудеров:</b>\n{top_lines}"
        )
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_panel")]
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
        text = "👥 <b>Юзеры</b>\n\nПока никого нет."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")]
        ])
    else:
        lines = []
        for u in chunk:
            uname = f"@{u.username}" if u.username else "(нет юзернейма)"
            status = "🟢" if u.chat_id in active_chat_users else "⚫️"
            lines.append(
                f"{status} <b>{u.full_name}</b> {uname}\n"
                f"  💬 {u.msg_count} сообщ. | 🕐 {u.last_seen.strftime('%d.%m %H:%M')}"
            )
        text = f"👥 <b>Список пользователей:</b>\n\n" + "\n\n".join(lines)
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
        f"📝 <b>Текст старта:</b>\n\n{greeting_text}",
        parse_mode="HTML",
    )

@dp.callback_query(F.data == "edit_greeting")
async def cb_edit_greeting(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "✏️ Введи новое приветствие для команды /start.\n\n"
        "Отмена — /cancel",
    )
    await state.set_state(AdminStates.waiting_for_greeting)

@dp.message(Command("cancel"), AdminStates.waiting_for_greeting)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Изменение отменено.", reply_markup=admin_panel_keyboard())

@dp.message(AdminStates.waiting_for_greeting)
async def receive_new_greeting(message: Message, state: FSMContext) -> None:
    global greeting_text
    greeting_text = message.text or greeting_text
    await state.clear()
    await message.answer(
        f"✅ Текст обновлен!\n\n<b>Теперь так:</b>\n{greeting_text}",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )

# ──────────────────────────────────────────────
# Ответ админа пользователю
# ──────────────────────────────────────────────

@dp.message(is_admin_filter, F.reply_to_message)
async def handle_admin_reply(message: Message) -> None:
    replied_id = message.reply_to_message.message_id
    user_chat_id = forward_map.get(replied_id)

    if user_chat_id is None:
        await message.answer("⚠️ Куда отправлять? Не могу найти юзера.")
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
            await message.answer("Такие файлы отправлять обратно пока не умею.")
            return
        await message.answer("✅ Ответ улетел.")
    except Exception as e:
        await message.answer(f"❌ Не отправилось: {e}")

# ──────────────────────────────────────────────
# Пересылка сообщений админу
# ──────────────────────────────────────────────

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
        logger.warning("Admin chat ID не настроен.")
        return

    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(нет юзернейма)"

    reply_context = ""
    if message.reply_to_message:
        quoted = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or "(файл)"
        )
        reply_context = f"↩️ <i>В ответ на:</i> «{quoted[:100]}»\n\n"

    header = (
        f"📨 <b>От: {user.full_name}</b> {username_part}\n"
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
            sent = await bot.send_message(chat_id=admin_chat_id, text=header + "[Что-то непонятное]", parse_mode="HTML")

        forward_map[sent.message_id] = message.chat.id

    except Exception as e:
        logger.error(f"Ошибка пересылки: {e}")

# ──────────────────────────────────────────────
# Игра в кости и кастомные дерзкие фразы
# ──────────────────────────────────────────────

@dp.message(is_user_filter, F.text == BTN_START)
async def btn_start(message: Message) -> None:
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(is_user_filter, F.text == BTN_LUCK)
async def btn_luck(message: Message) -> None:
    await cmd_luck(message)

@dp.message(Command("luck"))
async def cmd_luck(message: Message) -> None:
    try:
        await message.answer("Ха, решил испытать удачу? Ну давай, кидаем кости. Посмотрим, кто тут босс! 👀")
        user_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        bot_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        
        # Ждем пока кубики докрутятся
        await asyncio.sleep(4)
        u = user_dice.dice.value
        b = bot_dice.dice.value
        
        if u > b:
            result = (
                "Чё-о-о? Ты выиграл? 😳 Ну ладно, значит просто повезло, чистый рандом! "
                "Не думай, что ты реально круче. Давай еще раз, если не струсил!"
            )
        elif u < b:
            result = (
                "АХАХАХ ХА-ХА ЛОХ, ТЫ ПРОИГРАЛ! 🤭 На что ты вообще надеялся? "
                "Против моих кубиков у тебя нет ни единого шанса. Иди тренируйся!"
            )
        else:
            result = (
                "Ничья! 🤔 Равные цифры, но чисто потому, что я поддался. "
                "Перекидывай давай, надо решить, кто кого!"
            )
        await message.answer(f"Твой результат: {u} 🎰 Мой результат: {b}\n\n{result}")
    except Exception as e:
        logger.error(f"/luck error: {e}")
        await message.answer(f"Ой, кубики сломались: {e}")

@dp.message(is_user_filter, F.text.startswith("/"))
async def handle_unknown_command(message: Message) -> None:
    await message.answer(
        "Ты какую-то дичь написал, я таких команд не знаю. Вот, тыкай сюда:\n\n"
        "/start — Перезапуск\n"
        f"/chat — {BTN_CHAT}\n"
        f"/tracks — {BTN_TRACKS}\n"
        "/luck — Кости"
    )

@dp.message(is_user_filter)
async def handle_user_message(message: Message) -> None:
    if message.chat.id not in active_chat_users:
        return
    track_user(message)
    await forward_to_admin(message)

# ──────────────────────────────────────────────
# Заглушка веб-сервера для Render (Порт 10000)
# ──────────────────────────────────────────────

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот IvanFucken онлайн!".encode("utf-8"))

    def log_message(self, format, *args):
        return

def run_health_check_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info(f"Встроенный веб-сервер запущен на порту {PORT}")
    httpd.serve_forever()

# ──────────────────────────────────────────────
# Запуск бота
# ──────────────────────────────────────────────

async def setup_commands() -> None:
    user_commands = [
        BotCommand(command="start",  description="👋 Начать диалог"),
        BotCommand(command="chat",   description=f"{BTN_CHAT}"),
        BotCommand(command="tracks", description=f"{BTN_TRACKS}"),
        BotCommand(command="luck",   description="🎲 Кинуть кость"),
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
    logger.info("Starting new bot...")
    
    # Запуск фонового сервера для прохождения проверок на бесплатном Render
    threading.Thread(target=run_health_check_server, daemon=True).start()
    
    await setup_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
