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
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ В ПАМЯТИ ---
users = {}          # Хранилище пользователей: {user_id: UserInfo}
tracks_db = []      # Динамический список треков: [{"name": "...", "file_id": "..."}]
forward_map = {}    # Карта для ответов: {message_id_админа: chat_id_юзера}
greeting_text = "✌️ Здарова! Я новый бот. Можешь послушать мои треки. А если просто напишешь мне сообщение — его сразу прочитает админ!"

@dataclass
class UserInfo:
    chat_id: int
    full_name: str
    username: str | None
    first_seen: datetime = field(default_factory=datetime.now)

# Состояния FSM для админки
class AdminStates(StatesGroup):
    waiting_for_track_file = State()
    waiting_for_track_name = State()
    waiting_for_broadcast = State()

# --- КЛАВИАТУРЫ ---
def get_admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Управление треками", callback_data="manage_tracks")],
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="view_stats")]
    ])

def get_user_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 Послушать треки", callback_data="list_tracks")]
    ])

def track_user(message: Message):
    """Регистрирует пользователя в памяти бота при взаимодействии"""
    u = message.from_user
    if u and u.id != ADMIN_ID and u.id not in users:
        users[u.id] = UserInfo(chat_id=message.chat.id, full_name=u.full_name, username=u.username)

# --- ХЭНДЛЕРЫ КОМАНД ---
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        await setup_commands()
        await message.answer(
            "👋 Привет, босс! Твоя админка готова.\n\n"
            "⚡️ <b>Автоматический чат активен:</b> всё, что пишут юзеры, падает сюда.\n"
            "Чтобы ответить юзеру — сделай <b>REPLY (Ответ)</b> на его сообщение.\n\n"
            "Используй кнопки ниже для управления треками и рассылкой.",
            parse_mode="HTML",
            reply_markup=get_admin_kb()
        )
    else:
        track_user(message)
        await message.answer(greeting_text, reply_markup=get_user_kb())

@dp.message(Command("panel"))
async def panel_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

# --- ДИНАМИЧЕСКОЕ УПРАВЛЕНИЕ ТРЕКАМИ ---
@dp.callback_query(F.data == "manage_tracks")
async def manage_tracks(callback: CallbackQuery):
    await callback.message.edit_text(
        f"🎵 <b>Управление треками</b>\n\nВсего треков в панели: {len(tracks_db)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить новый трек", callback_data="add_track")],
            [InlineKeyboardButton(text="🗑 Очистить все треки", callback_data="clear_tracks")],
            [InlineKeyboardButton(text="↩️ В меню", callback_data="back_to_admin")]
        ])
    )

@dp.callback_query(F.data == "add_track")
async def add_track_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправь мне аудиофайл (.mp3), который хочешь добавить в бота:")
    await state.set_state(AdminStates.waiting_for_track_file)

@dp.message(AdminStates.waiting_for_track_file, F.audio)
async def get_track_file(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id)
    await message.answer("Файл получен! Теперь напиши название трека (так его будут видеть пользователи):")
    await state.set_state(AdminStates.waiting_for_track_name)

@dp.message(AdminStates.waiting_for_track_name, F.text)
async def get_track_name(message: Message, state: FSMContext):
    data = await state.get_data()
    tracks_db.append({"name": message.text, "file_id": data['file_id']})
    await state.clear()
    await message.answer(f"✅ Трек «<b>{message.text}</b>» успешно добавлен и доступен пользователям!", parse_mode="HTML", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "clear_tracks")
async def clear_tracks(callback: CallbackQuery):
    tracks_db.clear()
    await callback.message.edit_text("🗑 Все треки были удалены из памяти.", reply_markup=get_admin_kb())

# --- ПРОСЛУШИВАНИЕ ТРЕКОВ ЮЗЕРАМИ ---
@dp.callback_query(F.data == "list_tracks")
async def list_tracks(callback: CallbackQuery):
    if not tracks_db:
        await callback.answer("Пока нет доступных треков! Админ скоро их добавит.", show_alert=True)
        return
    
    kb_list = [[InlineKeyboardButton(text=f"🎵 {t['name']}", callback_data=f"play:{i}")] for i, t in enumerate(tracks_db)]
    await callback.message.edit_text("🔥 <b>Выбирай любой трек IvanFucken:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("play:"))
async def play_track(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    await callback.answer("Загружаю трек... 🎧")
    try:
        await bot.send_audio(
            chat_id=callback.message.chat.id,
            audio=tracks_db[idx]['file_id'],
            caption="Понравился трек? Качай и делись с кентами! 😎"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки аудио: {e}")

# --- МАССОВАЯ РАССЫЛКА ---
@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 <b>Режим рассылки</b>\n\nОтправь сообщение (текст, фото или файл), которое улетит ВСЕМ юзерам.\nДля отмены введи /cancel", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast, Command("cancel"))
async def broadcast_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=get_admin_kb())

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    all_users = list(users.keys())
    if not all_users:
        await message.answer("👥 База пользователей пуста. Некому отправлять.", reply_markup=get_admin_kb())
        return

    await message.answer(f"🚀 Запускаю рассылку на {len(all_users)} пользователей...")
    success, failed = 0, 0

    for uid in all_users:
        try:
            if message.text:
                await bot.send_message(chat_id=uid, text=message.text)
            elif message.photo:
                await bot.send_photo(chat_id=uid, photo=message.photo[-1].file_id, caption=message.caption)
            elif message.audio:
                await bot.send_audio(chat_id=uid, audio=message.audio.file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(chat_id=uid, document=message.document.file_id, caption=message.caption)
            success += 1
            await asyncio.sleep(0.05)  # Защита от лимитов Telegram
        except Exception:
            failed += 1

    await message.answer(f"📊 <b>Рассылка завершена!</b>\n\n✅ Успешно: {success}\n❌ Заблокировали бота: {failed}", parse_mode="HTML", reply_markup=get_admin_kb())

# --- СТАТИСТИКА БОТА ---
@dp.callback_query(F.data == "view_stats")
async def view_stats(callback: CallbackQuery):
    await callback.message.edit_text(
        f"📊 <b>Статистика IvanFuckenBot</b>\n\n"
        f"👥 Уникальных юзеров в памяти: <b>{len(users)}</b>\n"
        f"🎵 Загружено треков в панель: <b>{len(tracks_db)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ В меню", callback_data="back_to_admin")]])
    )

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

# --- АВТОМАТИЧЕСКИЙ ЧАТ (ПЕРЕСЫЛКА АДМИНУ) ---
@dp.message(F.chat.id != ADMIN_ID)
async def forward_to_admin(message: Message):
    track_user(message)
    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(нет юзернейма)"
    header = f"📨 <b>От: {user.full_name}</b> {username_part}\nID: <code>{user.id}</code>\n\n"

    try:
        if message.text:
            sent = await bot.send_message(chat_id=ADMIN_ID, text=header + message.text, parse_mode="HTML")
        elif message.photo:
            sent = await bot.send_photo(chat_id=ADMIN_ID, photo=message.photo[-1].file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.audio:
            sent = await bot.send_audio(chat_id=ADMIN_ID, audio=message.audio.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.voice:
            sent = await bot.send_voice(chat_id=ADMIN_ID, photo=message.voice.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        elif message.document:
            sent = await bot.send_document(chat_id=ADMIN_ID, document=message.document.file_id, caption=header + (message.caption or ""), parse_mode="HTML")
        else:
            sent = await bot.send_message(chat_id=ADMIN_ID, text=header + "[Другой тип медиафайла]", parse_mode="HTML")

        # Запоминаем связку сообщения, чтобы админ мог ответить реплаем
        forward_map[sent.message_id] = message.chat.id
    except Exception as e:
        logger.error(f"Ошибка пересылки админу: {e}")

# --- ОТВЕТ АДМИНА ЧЕРЕЗ REPLY (ОТВЕТ) ---
@dp.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def handle_admin_reply(message: Message):
    replied_id = message.reply_to_message.message_id
    user_chat_id = forward_map.get(replied_id)

    if user_chat_id is None:
        await message.answer("⚠️ Не удалось определить, какому пользователю ответить. Ответ пишется строго через функцию 'Ответить' (Reply) на пересланное сообщение.")
        return

    try:
        if message.text:
            await bot.send_message(chat_id=user_chat_id, text=message.text)
        elif message.photo:
            await bot.send_photo(chat_id=user_chat_id, photo=message.photo[-1].file_id, caption=message.caption)
        elif message.audio:
            await bot.send_audio(chat_id=user_chat_id, audio=message.audio.file_id, caption=message.caption)
        elif message.document:
            await bot.send_document(chat_id=user_chat_id, document=message.document.file_id, caption=message.caption)
        await message.answer("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ. Ошибка: {e}")

# --- ВСТРОЕННЫЙ СЕРВЕР ДЛЯ RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот IvanFucken онлайн!".encode("utf-8"))
    def log_message(self, format, *args): return

def run_health_check_server():
    HTTPServer(("", PORT), HealthCheckHandler).serve_forever()

async def setup_commands():
    user_cmds = [BotCommand(command="start", description="👋 Старт / Обновить")]
    admin_cmds = user_cmds + [BotCommand(command="panel", description="⚙️ Админ-панель")]
    await bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
    if ADMIN_ID:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except Exception: pass

async def main():
    logger.info("Запуск новой версии бота...")
    threading.Thread(target=run_health_check_server, daemon=True).start()
    await setup_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
