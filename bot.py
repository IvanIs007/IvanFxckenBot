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
    ReplyKeyboardMarkup, KeyboardButton,
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

# Настройки и база данных в памяти
greeting_text: str = "✌️ Здарова! Я новый бот. Можешь чекнуть мои треки или рискнуть сыграть со мной в кости. А если просто напишешь мне сообщение — его сразу прочитает админ!"
forward_map: dict[int, int] = {}  # Карта: message_id админа -> chat_id юзера
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None

USERS_PER_PAGE = 10

BTN_TRACKS  = "🎵 Треки IvanFucken"
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

# Состояния FSM для админки
class AdminStates(StatesGroup):
    waiting_for_greeting = State()
    waiting_for_broadcast = State()
    waiting_for_user_id = State()
    waiting_for_direct_msg = State()

# Фильтры проверки ролей
async def is_admin_filter(message: Message) -> bool:
    if ADMIN_ID and message.from_user and message.from_user.id == ADMIN_ID:
        return True
    return bool(message.from_user and message.from_user.username == ADMIN_USERNAME)

async def is_user_filter(message: Message) -> bool:
    return not await is_admin_filter(message)

# ──────────────────────────────────────────────
# Клавиатуры
# ──────────────────────────────────────────────

def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TRACKS)],
            [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_START)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Пиши всё что хочешь, я передам...",
    )

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="👥 Юзеры", callback_data="users_p:0"),
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast"),
            InlineKeyboardButton(text="👤 Написать юзеру", callback_data="direct_send"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить старт", callback_data="edit_greeting"),
            InlineKeyboardButton(text="👁 Чекнуть старт", callback_data="show_greeting"),
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
# База Данных твоих треков (Сюда вставлять ID)
# ──────────────────────────────────────────────

def tracks_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 NOZHKI", callback_data="track:polling")],
        [InlineKeyboardButton(text="", callback_data="track:port")],
        [InlineKeyboardButton(text="")],
        [InlineKeyboardButton(text="")],
        [InlineKeyboardButton(text="", callback_data="track:dice")],
    ])

def get_tracks_database() -> dict[str, str]:
    """
    Сюда ты будешь вписывать полученные от бота file_id.
    Просто сотри текст ЗАМЕНИ_НА_FILE_ID и вставь туда длинную строку, которую пришлет бот.
    """
    return {
        "polling": "CQACAgIAAxkBAAPPajlN7nMJSpTpJPIYjN6zEwovTaAAAhl3AAL_e7FJilKv06czpLg8BA",
        "port": "ЗАМЕНИ_НА_FILE_ID",
        "logs": "ЗАМЕНИ_НА_FILE_ID",
        "server": "ЗАМЕНИ_НА_FILE_ID",
        "dice": "ЗАМЕНИ_НА_FILE_ID",
    }

# ──────────────────────────────────────────────
# Хэндлеры команд админа
# ──────────────────────────────────────────────

@dp.message(CommandStart(), is_admin_filter)
async def cmd_start_admin(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await setup_commands()
    await message.answer(
        f"👋 Здарова, босс! Твоя админка готова.\n"
        f"Твой chat ID зафиксирован: <code>{message.chat.id}</code>\n\n"
        "⚡️ <b>Автоматический чат активен:</b> всё, что пишут юзеры, летит сюда.\n"
        "Чтобы ответить пользователю — просто сделай <b>REPLY (Ответ)</b> на сообщение.\n\n"
        "📥 <b>Перехват треков включен:</b> если скинешь в бота любой .mp3 файл, он пришлет тебе его ID для базы данных треков.\n\n"
        "Команда /panel откроет настройки рассылок.",
        parse_mode="HTML",
    )

@dp.message(CommandStart(), is_user_filter)
async def cmd_start_user(message: Message) -> None:
    track_user(message)
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(Command("panel"), is_admin_filter)
async def cmd_panel(message: Message) -> None:
    global admin_chat_id
    admin_chat_id = message.chat.id
    await message.answer("⚙️ <b>Панель управления IvanFuckenBot</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())

# ──────────────────────────────────────────────
# Логика пересылки и автоматического перехвата ID треков
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
        return

    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(нет юзернейма)"
    header = f"📨 <b>От: {user.full_name}</b> {username_part}\nID: <code>{user.id}</code>\n\n"

    try:
        if message.text:
            sent = await bot.send_message(chat_id=admin_chat_id, text=header + message.text, parse_mode="HTML")
        
        elif message.audio:  # Если тебе или боту прислали аудиофайл
            sent = await bot.send_audio(chat_id=admin_chat_id, audio=message.audio.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
            # Сразу же дублируем админу чистый file_id отдельным сообщением
            await bot.send_message(
                chat_id=admin_chat_id,
                text=f"🎵 <b>ID аудиозаписи для вставки в код:</b>\n<code>{message.audio.file_id}</code>\n\n<i>Нажми на код выше, чтобы скопировать его.</i>",
                parse_mode="HTML"
            )
            
        elif message.document:  # На случай, если mp3 скинули файлом без сжатия
            sent = await bot.send_document(chat_id=admin_chat_id, document=message.document.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
            if message.document.mime_type and "audio" in message.document.mime_type:
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text=f"📄 <b>ID аудио-документа для вставки в код:</b>\n<code>{message.document.file_id}</code>",
                    parse_mode="HTML"
                )
                
        elif message.photo:
            sent = await bot.send_photo(chat_id=admin_chat_id, photo=message.photo[-1].file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.voice:
            sent = await bot.send_voice(chat_id=admin_chat_id, voice=message.voice.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.sticker:
            await bot.send_message(chat_id=admin_chat_id, text=header + f"[Стикер {message.sticker.emoji or ''}]", parse_mode="HTML")
            sent = await bot.send_sticker(chat_id=admin_chat_id, sticker=message.sticker.file_id)
        else:
            sent = await bot.send_message(chat_id=admin_chat_id, text=header + "[Другой тип медиафайла]", parse_mode="HTML")

        forward_map[sent.message_id] = message.chat.id
    except Exception as e:
        logger.error(f"Ошибка авто-пересылки админу: {e}")

# Ответ админа пользователю через функцию Reply (Ответ)
@dp.message(is_admin_filter, F.reply_to_message)
async def handle_admin_reply(message: Message) -> None:
    replied_id = message.reply_to_message.message_id
    user_chat_id = forward_map.get(replied_id)

    if user_chat_id is None:
        await message.answer("⚠️ Не могу сопоставить этот реплай с пользователем. Используй отправку по ID через панель.")
        return

    try:
        if message.text:
            await bot.send_message(chat_id=user_chat_id, text=message.text)
        elif message.photo:
            await bot.send_photo(chat_id=user_chat_id, photo=message.photo[-1].file_id, caption=message.caption)
        elif message.document:
            await bot.send_document(chat_id=user_chat_id, document=message.document.file_id, caption=message.caption)
        elif message.audio:
            await bot.send_audio(chat_id=user_chat_id, audio=message.audio.file_id, caption=message.caption)
        elif message.voice:
            await bot.send_voice(chat_id=user_chat_id, voice=message.voice.file_id, caption=message.caption)
        else:
            await message.answer("Данный тип сообщений обратно не поддерживается.")
            return
        await message.answer("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")

# ──────────────────────────────────────────────
# Функции админки (Рассылка, Прямые сообщения)
# ──────────────────────────────────────────────

@dp.callback_query(F.data == "back_panel")
async def cb_back_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer("⚙️ <b>Панель управления IvanFuckenBot</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())

# Массовая рассылка всем юзерам из кэша
@dp.callback_query(F.data == "broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("📢 <b>Режим массовой рассылки</b>\n\nОтправь мне сообщение (текст, фото с описанием или документ), которое улетит <b>ВСЕМ</b> пользователям бота.\n\nДля отмены введи /cancel", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast, Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=admin_panel_keyboard())

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    all_users = list(users.keys())
    if not all_users:
        await message.answer("👥 База пользователей пуста. Некому отправлять.", reply_markup=admin_panel_keyboard())
        return

    await message.answer(f"🚀 Запускаю рассылку на {len(all_users)} пользователей...")
    success, failed = 0, 0

    for uid in all_users:
        try:
            if message.text:
                await bot.send_message(chat_id=uid, text=message.text)
            elif message.photo:
                await bot.send_photo(chat_id=uid, photo=message.photo[-1].file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(chat_id=uid, document=message.document.file_id, caption=message.caption)
            elif message.audio:
                await bot.send_audio(chat_id=uid, audio=message.audio.file_id, caption=message.caption)
            elif message.voice:
                await bot.send_voice(chat_id=uid, voice=message.voice.file_id, caption=message.caption)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(f"📊 <b>Рассылка завершена!</b>\n\n✅ Успешно: {success}\n❌ Ошибки (заблокировали): {failed}", reply_markup=admin_panel_keyboard())

# Отправка сообщения по ID
@dp.callback_query(F.data == "direct_send")
async def cb_direct_send(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("👤 <b>Отправка сообщения конкретному юзеру</b>\n\nВведите цифровой Telegram ID пользователя:", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_user_id)

@dp.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_panel_keyboard())
        return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен состоять только из цифр. Попробуй ещё раз или отмени команду с помощью /cancel:")
        return
    await state.update_data(target_uid=int(message.text))
    await message.answer(f"ID принят! Теперь отправь сообщение (текст, фото, аудио или документ), которое нужно передать пользователю {message.text}:")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.message(AdminStates.waiting_for_direct_msg)
async def process_direct_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()

    try:
        if message.text:
            await bot.send_message(chat_id=uid, text=message.text)
        elif message.photo:
            await bot.send_photo(chat_id=uid, photo=message.photo[-1].file_id, caption=message.caption)
        elif message.document:
            await bot.send_document(chat_id=uid, document=message.document.file_id, caption=message.caption)
        elif message.audio:
            await bot.send_audio(chat_id=uid, audio=message.audio.file_id, caption=message.caption)
        elif message.voice:
            await bot.send_voice(chat_id=uid, voice=message.voice.file_id, caption=message.caption)
        await message.answer(f"✅ Сообщение доставлено пользователю {uid}.", reply_markup=admin_panel_keyboard())
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить на ID {uid}. Ошибка: {e}", reply_markup=admin_panel_keyboard())

# Статистика и управление пользователями
@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    total_users = len(users)
    if total_users == 0:
        text = "📊 <b>Статистика</b>\n\nПока в базе никого нет."
    else:
        top = sorted(users.values(), key=lambda u: u.msg_count, reverse=True)[:5]
        top_lines = "\n".join(f"  {i+1}. {u.full_name} — {u.msg_count} сообщ." for i, u in enumerate(top))
        last_active = max(users.values(), key=lambda u: u.last_seen)
        text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Уникальных юзеров в базе: <b>{total_users}</b>\n"
            f"💬 Всего сообщений обработано: <b>{total_messages}</b>\n"
            f"🕐 Последний активный: <b>{last_active.full_name}</b> ({last_active.last_seen.strftime('%d.%m %H:%M')})\n\n"
            f"🏆 <b>Топ флудеров:</b>\n{top_lines}"
        )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="back_panel")]]))

@dp.callback_query(F.data.startswith("users_p:"))
async def cb_users_page(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[1])
    sorted_users = sorted(users.values(), key=lambda u: u.last_seen, reverse=True)
    total_pages = max(1, (len(sorted_users) + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = sorted_users[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]

    if not chunk:
        text = "👥 <b>Юзеры</b>\n\nПока никого."
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Панель", callback_data="back_panel")]])
    else:
        lines = []
        for u in chunk:
            uname = f"@{u.username}" if u.username else "(нет юзернейма)"
            lines.append(f"⚫️ <b>{u.full_name}</b> {uname}\n  ID: <code>{u.chat_id}</code> | 💬 {u.msg_count} соб. | 🕐 {u.last_seen.strftime('%d.%m %H:%M')}")
        text = f"👥 <b>Список пользователей:</b>\n\n" + "\n\n".join(lines)
        markup = users_page_keyboard(page, total_pages)

    await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()

@dp.callback_query(F.data == "show_greeting")
async def cb_show_greeting(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(f"📝 <b>Текущий текст /start:</b>\n\n{greeting_text}", parse_mode="HTML")

@dp.callback_query(F.data == "edit_greeting")
async def cb_edit_greeting(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("✏️ Введи новое приветствие для команды /start.\n\nОтмена — /cancel")
    await state.set_state(AdminStates.waiting_for_greeting)

@dp.message(AdminStates.waiting_for_greeting)
async def receive_new_greeting(message: Message, state: FSMContext) -> None:
    global greeting_text
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Изменение отменено.", reply_markup=admin_panel_keyboard())
        return
    greeting_text = message.text or greeting_text
    await state.clear()
    await message.answer(f"✅ Текст обновлен!\n\n<b>Теперь так:</b>\n{greeting_text}", parse_mode="HTML", reply_markup=admin_panel_keyboard())

# ──────────────────────────────────────────────
# Логика отправки треков пользователям
# ──────────────────────────────────────────────

async def show_tracks(message: Message) -> None:
    await message.answer(
        "🔥 <b>Выбирай любой трек IvanFucken ниже, и я скину тебе MP3:</b>",
        parse_mode="HTML",
        reply_markup=tracks_inline_keyboard()
    )

@dp.message(Command("tracks"), is_user_filter)
async def cmd_tracks(message: Message) -> None:
    track_user(message)
    await show_tracks(message)

@dp.message(is_user_filter, F.text == BTN_TRACKS)
async def btn_tracks(message: Message) -> None:
    track_user(message)
    await show_tracks(message)

# Хэндлер обработки нажатий на кнопки треков
@dp.callback_query(F.data.startswith("track:"))
async def handle_track_request(callback: CallbackQuery) -> None:
    await callback.answer("Отправляю трек... 🎧")
    
    track_key = callback.data.split(":")[1]
    chat_id = callback.message.chat.id
    tracks_database = get_tracks_database()
    file_to_send = tracks_database.get(track_key)

    if not file_to_send or "ЗАМЕНИ_НА" in file_to_send:
        await callback.message.answer("⚠️ Этот трек еще не загружен на сервер. Админ скоро всё поправит!")
        return

    try:
        await bot.send_audio(
            chat_id=chat_id, 
            audio=file_to_send,
            caption="Понравился трек? Качай и кидай друзьям! 😎"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки аудио: {e}")
        await callback.message.answer("❌ Не удалось отправить файл. Что-то пошло не так.")

# ──────────────────────────────────────────────
# Игра в кости и остальные функции
# ──────────────────────────────────────────────

@dp.message(Command("luck"), is_user_filter)
@dp.message(is_user_filter, F.text == BTN_LUCK)
async def cmd_luck(message: Message) -> None:
    track_user(message)
    try:
        await message.answer("Ха, решил испытать удачу? Ну давай, кидаем кости! 👀")
        user_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        bot_dice = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
        await asyncio.sleep(4)
        u, b = user_dice.dice.value, bot_dice.dice.value
        result = "Ты выиграл! 😳 Рандом на твоей стороне." if u > b else ("ТЫ ПРОИГРАЛ! 🤭 Против моих кубиков шансов нет." if u < b else "Ничья! 🤔 Я просто поддался.")
        await message.answer(f"Твой результат: {u} 🎰 Мой результат: {b}\n\n{result}")
    except Exception as e:
        logger.error(f"/luck error: {e}")

@dp.message(is_user_filter, F.text == BTN_START)
async def btn_start(message: Message) -> None:
    track_user(message)
    await message.answer(greeting_text, reply_markup=user_keyboard())

# Ловим все остальные сообщения от обычных юзеров и шлем админу
@dp.message(is_user_filter)
async def handle_user_message(message: Message) -> None:
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

async def setup_commands() -> None:
    user_commands = [
        BotCommand(command="start",  description="👋 Начать диалог"),
        BotCommand(command="tracks", description="🎵 Послушать треки"),
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
    logger.info("Starting new bot version...")
    threading.Thread(target=run_health_check_server, daemon=True).start()
    await setup_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
