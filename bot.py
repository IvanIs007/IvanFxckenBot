import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗЫ ДАННЫХ В ПАМЯТИ ---
users = {}          # {user_id: full_name} — общая база для рассылки
tracks_db = []      # [{"name": "...", "file_id": "..."}] — список треков
recent_chats = {}   # {user_id: full_name} — история недавних диалогов админа
forward_map = {}    # {message_id_админа: chat_id_юзера} — для реплай-чата

class AdminStates(StatesGroup):
    waiting_for_track_file = State()
    waiting_for_track_name = State()
    waiting_for_broadcast = State()
    waiting_for_direct_uid = State()
    waiting_for_direct_msg = State()

# --- КЛАВИАТУРЫ ---
def get_admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Треки", callback_data="manage_tracks"), InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast_start")],
        [InlineKeyboardButton(text="📝 Недавние диалоги", callback_data="recent_chats"), InlineKeyboardButton(text="➕ Новое ID", callback_data="direct_send_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="view_stats"), InlineKeyboardButton(text="🎲 Кинуть кость", callback_data="dice")]
    ])

def get_user_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 Послушать треки", callback_data="list_tracks")],
        [InlineKeyboardButton(text="🎲 Кинуть кость", callback_data="dice")]
    ])

# --- КОМАНДА СТАРТ ---
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "👋 Привет, админ! Твоя панель управления готова.\n\n"
            "• Чтобы ответить пользователю — сделай <b>REPLY (Ответ)</b> на пересланное сообщение.\n"
            "• Кнопка «Недавние диалоги» покажет список тех, с кем ты общался.",
            parse_mode="HTML",
            reply_markup=get_admin_kb()
        )
    else:
        users[message.from_user.id] = message.from_user.full_name
        recent_chats[message.from_user.id] = message.from_user.full_name
        await message.answer(
            "✌️ Здарова! Я новый бот. Можешь послушать мои треки или рискнуть сыграть со мной в кости. А если просто напишешь мне сообщение — его сразу прочитает админ!",
            reply_markup=get_user_kb()
        )

@dp.message(Command("panel"))
async def panel_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

# --- КРУТЫЕ КОСТИ (DICE) ---
@dp.callback_query(F.data == "dice")
async def send_dice(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.message.answer("Ха, решил испытать удачу? Ну давай, кидаем кости! 👀")
    
    # Бросаем кубики для юзера и бота отдельно
    user_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    bot_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    
    # Ждем анимацию прокрутки (4 секунды)
    await asyncio.sleep(4)
    
    u = user_dice.dice.value
    b = bot_dice.dice.value
    
    if u > b:
        result = "Ты выиграл! 😳 Рандом на твоей стороне."
    elif u < b:
        result = "ТЫ ПРОИГРАЛ! 🤭 Против моих кубиков шансов нет."
    else:
        result = "Ничья! 🤔 Я просто поддался."
        
    await bot.send_message(chat_id=chat_id, text=f"Твой результат: {u} 🎰 Мой результат: {b}\n\n{result}")

# --- ИСТОРИЯ И НЕДАВНИЕ ДИАЛОГИ ---
@dp.callback_query(F.data == "recent_chats")
async def show_recent(callback: CallbackQuery):
    if not recent_chats:
        await callback.answer("Список недавних диалогов пока пуст!", show_alert=True)
        return
        
    kb_buttons = [[InlineKeyboardButton(text=f"👤 {name}", callback_data=f"chat_with:{uid}")] for uid, name in recent_chats.items()]
    kb_buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_admin")])
    
    await callback.message.edit_text("📝 <b>Выбери пользователя из недавних для отправки сообщения:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@dp.callback_query(F.data.startswith("chat_with:"))
async def start_chat_with(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split(":")[1])
    name = recent_chats.get(uid, "Пользователь")
    await state.update_data(target_uid=uid)
    await callback.message.answer(f"🗣 Режим прямой отправки пользователю <b>{name}</b> (ID: {uid}).\n\nОтправь мне сообщение (текст, фото или файл), которое нужно передать:", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_direct_msg)

# --- ОТПРАВКА НОВОМУ ПОЛЬЗОВАТЕЛЮ ПО ID ---
@dp.callback_query(F.data == "direct_send_start")
async def direct_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 Введи цифровой Telegram ID пользователя, которому хочешь написать:")
    await state.set_state(AdminStates.waiting_for_direct_uid)

@dp.message(AdminStates.waiting_for_direct_uid)
async def get_uid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ ID должен состоять только из цифр. Введи ещё раз:")
        return
    uid = int(message.text)
    name = users.get(uid, f"Юзер {uid}")
    recent_chats[uid] = name  # Запоминаем в недавние диалоги
    
    await state.update_data(target_uid=uid)
    await message.answer(f"ID принят! Теперь отправь сообщение (текст, фото или файл), которое нужно передать пользователю {name}:")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.message(AdminStates.waiting_for_direct_msg)
async def send_direct_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()
    try:
        await message.send_copy(chat_id=uid)
        await message.answer("✅ Сообщение успешно доставлено!", reply_markup=get_admin_kb())
    except Exception as e:
        await message.answer(f"❌ Не удалось доставить сообщение. Ошибка: {e}", reply_markup=get_admin_kb())

# --- ДИНАМИЧЕСКОЕ УПРАВЛЕНИЕ ТРЕКАМИ ---
@dp.callback_query(F.data == "manage_tracks")
async def manage_tracks(callback: CallbackQuery):
    await callback.message.edit_text(
        f"🎵 <b>Управление треками</b>\n\nВсего треков в базе: {len(tracks_db)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить трек", callback_data="add_track")],
            [InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_tracks")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_admin")]
        ])
    )

@dp.callback_query(F.data == "add_track")
async def add_track_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли мне mp3-файл трека:")
    await state.set_state(AdminStates.waiting_for_track_file)

@dp.message(AdminStates.waiting_for_track_file, F.audio)
async def get_track_file(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id)
    await message.answer("Файл получен! Теперь напиши его название для отображения в кнопках:")
    await state.set_state(AdminStates.waiting_for_track_name)

@dp.message(AdminStates.waiting_for_track_name, F.text)
async def get_track_name(message: Message, state: FSMContext):
    data = await state.get_data()
    tracks_db.append({"name": message.text, "file_id": data['file_id']})
    await state.clear()
    await message.answer(f"✅ Трек «<b>{message.text}</b>» успешно добавлен в бота!", parse_mode="HTML", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "clear_tracks")
async def clear_tracks(callback: CallbackQuery):
    tracks_db.clear()
    await callback.message.edit_text("🗑 Все треки удалены из памяти бота.", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "list_tracks")
async def list_tracks(callback: CallbackQuery):
    if not tracks_db:
        await callback.answer("Пока нет доступных треков! Загляни позже.", show_alert=True)
        return
    kb_list = [[InlineKeyboardButton(text=f"🎵 {t['name']}", callback_data=f"play:{i}")] for i, t in enumerate(tracks_db)]
    await callback.message.edit_text("🔥 <b>Выбирай любой трек IvanFucken:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("play:"))
async def play_track(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    await callback.answer("Загружаю трек... 🎧")
    try:
        await bot.send_audio(callback.message.chat.id, tracks_db[idx]['file_id'], caption="Понравился трек? Качай и делись с кентами! 😎")
    except Exception as e:
        logger.error(f"Ошибка воспроизведения: {e}")

# --- МАССОВАЯ РАССЫЛКА ---
@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Отправь мне любое сообщение (текст, фото или файл), которое улетит абсолютно ВСЕМ юзерам:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    if not users:
        await message.answer("👥 База пуста, рассылать некому.", reply_markup=get_admin_kb())
        return
    success = 0
    for uid in list(users.keys()):
        try:
            await message.send_copy(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📊 Рассылка завершена! Успешно доставлено сообщений: {success}", reply_markup=get_admin_kb())

# --- СТАТИСТИКА И НАВИГАЦИЯ ---
@dp.callback_query(F.data == "view_stats")
async def view_stats(callback: CallbackQuery):
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных юзеров в сессии: <b>{len(users)}</b>\n"
        f"🎵 Загружено треков в меню: <b>{len(tracks_db)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="back_admin")]])
    )

@dp.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

# --- АВТОМАТИЧЕСКИЙ ЧАТ (ПЕРЕСЫЛКА СООБЩЕНИЙ АДМИНУ) ---
@dp.message(F.chat.id != ADMIN_ID)
async def chat_flow(message: Message):
    # Регистрируем пользователя во всех базах данных
    users[message.from_user.id] = message.from_user.full_name
    recent_chats[message.from_user.id] = message.from_user.full_name
    
    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(нет юзернейма)"
    header = f"📨 <b>От: {user.full_name}</b> {username_part}\nID: <code>{user.id}</code>\n\n"
    
    # Отправляем админу сначала заголовок с ID, а следом само сообщение (копию)
    await bot.send_message(chat_id=ADMIN_ID, text=header, parse_mode="HTML")
    msg = await message.send_copy(chat_id=ADMIN_ID)
    forward_map[msg.message_id] = message.chat.id

# --- ОТВЕТ АДМИНА ПО REPLY ---
@dp.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message):
    uid = forward_map.get(message.reply_to_message.message_id)
    if uid:
        try:
            recent_chats[uid] = users.get(uid, f"Юзер {uid}") # Актуализируем в недавних
            await message.send_copy(chat_id=uid)
            await message.answer("✅ Ответ успешно отправлен пользователю.")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить ответ. Ошибка: {e}")
    else:
        await message.answer("⚠️ Бот не может определить юзера по этому реплаю. Пожалуйста, используй кнопку «Недавние диалоги» или «Новое ID» для прямой отправки.")

# --- ВЕБ-СЕРВЕР ДЛЯ ЗАКРЫТИЯ ПОРТА (ДЛЯ RENDER) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(s):
        s.send_response(200)
        s.end_headers()
        s.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_server():
    HTTPServer(("", PORT), HealthCheck).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    asyncio.run(dp.start_polling(bot))

