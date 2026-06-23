import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Инициализация клиента Grok (через библиотеку openai)
from openai import AsyncOpenAI

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
XAI_API_KEY = os.environ.get("XAI_API_KEY", "") # Твой ключ от Grok API

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Инициализируем клиент Grok, если ключ указан
grok_client = AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1") if XAI_API_KEY else None

# --- БАЗЫ ДАННЫХ В ПАМЯТИ ---
users = {}          # {user_id: full_name}
tracks_db = []      # [{"name": "...", "file_id": "..."}]
recent_chats = {}   # {user_id: full_name}
forward_map = {}    # {message_id_админа: chat_id_юзера}
ai_mode_users = set() # Сет для ID пользователей, у которых включен ИИ-режим

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
        [InlineKeyboardButton(text="🤖 Спросить Grok", callback_data="grok_admin"), InlineKeyboardButton(text="🎲 Кинуть кость", callback_data="dice")]
    ])

def get_user_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 Послушать треки", callback_data="list_tracks"), InlineKeyboardButton(text="🤖 Общение с ИИ", callback_data="grok_start")],
        [InlineKeyboardButton(text="🎲 Кинуть кость", callback_data="dice")]
    ])

def get_exit_ai_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Выйти из режима ИИ", callback_data="grok_stop")]
    ])

# --- РЕГИСТРАЦИЯ КОМАНД В МЕНЮ TELEGRAM ---
async def set_bot_commands():
    user_commands = [
        BotCommand(command="start", description="👋 Перезапустить бота"),
        BotCommand(command="tracks", description="🎧 Послушать треки IvanFucken"),
        BotCommand(command="grok", description="🤖 Включить режим общения с ИИ"),
        BotCommand(command="dice", description="🎲 Сыграть в кости с ботом")
    ]
    admin_commands = [
        BotCommand(command="start", description="👋 Перезапустить бота"),
        BotCommand(command="panel", description="⚙️ Главная админка"),
        BotCommand(command="tracks_control", description="🎵 Управление треками"),
        BotCommand(command="broadcast", description="📢 Сделать рассылку"),
        BotCommand(command="chats", description="📝 Недавние диалоги"),
        BotCommand(command="grok", description="🤖 Быстрый вопрос к Grok ИИ"),
        BotCommand(command="dice", description="🎲 Кинуть кость")
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    if ADMIN_ID:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except Exception as e:
            logger.error(f"Не удалось установить команды для админа: {e}")

# --- КОМАНДА СТАРТ ---
@dp.message(CommandStart())
async def start_cmd(message: Message):
    await set_bot_commands()
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "👋 Привет, админ! Твоя панель управления готова.\n\n"
            "• Чтобы ответить пользователю — сделай <b>REPLY (Ответ)</b> на пересланное сообщение.\n"
            "• Кнопка «Недавние диалоги» или команда /chats покажет список тех, с кем ты общался.",
            parse_mode="HTML",
            reply_markup=get_admin_kb()
        )
    else:
        users[message.from_user.id] = message.from_user.full_name
        recent_chats[message.from_user.id] = message.from_user.full_name
        await message.answer(
            "✌️ Здарова! Я новый бот. Можешь послушать мои треки, рискнуть сыграть со мной в кости или "
            "<b>пообщаться с искусственным интеллектом Grok</b>!\n\n"
            "Используй кнопки ниже или команды в меню: /tracks, /grok и /dice.",
            parse_mode="HTML",
            reply_markup=get_user_kb()
        )

# --- ЛОГИКА ВЗАИМОДЕЙСТВИЯ С GROK API ---
async def ask_grok(prompt: str) -> str:
    if not grok_client:
        return "❌ Ошибка: Grok API не настроен на сервере (отсутствует XAI_API_KEY)."
    try:
        response = await grok_client.chat.completions.create(
            model="grok-2-latest", # Или grok-beta / grok-2-mini в зависимости от доступности
            messages=[
                {"role": "system", "content": "Ты — крутой и полезный ИИ-ассистент в боте IvanFuckenBot. Отвечай кратко, емко и по делу."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка Grok API: {e}")
        return f"⚠️ Произошла ошибка при запросе к нейросети. Попробуй позже."

# --- КОМАНДЫ И CALLBACK ДЛЯ РЕЖИМА ИИ ---
@dp.message(Command("grok"))
async def grok_command(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        # У админа команда работает как одиночный запрос (например: /grok сколько планет)
        prompt = message.text.replace("/grok", "").strip()
        if not prompt:
            await message.answer("Использование для админа: <code>/grok твой вопрос</code>", parse_mode="HTML")
            return
        msg = await message.answer("🔄 Думаю...")
        reply = await ask_grok(prompt)
        await msg.edit_text(reply)
    else:
        # У юзера команда включает постоянный режим диалога
        ai_mode_users.add(message.from_user.id)
        await message.answer("🤖 <b>Режим общения с нейросетью Grok активирован!</b>\n\nПиши мне любые вопросы, я буду отвечать с помощью ИИ.", parse_mode="HTML", reply_markup=get_exit_ai_kb())

@dp.callback_query(F.data == "grok_start")
async def grok_start_callback(callback: CallbackQuery):
    await callback.answer()
    ai_mode_users.add(callback.from_user.id)
    await callback.message.answer("🤖 <b>Режим общения с нейросетью Grok активирован!</b>\n\nЗадавай свои вопросы:", parse_mode="HTML", reply_markup=get_exit_ai_kb())

@dp.callback_query(F.data == "grok_stop")
async def grok_stop_callback(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ai_mode_users:
        ai_mode_users.remove(callback.from_user.id)
    await callback.message.answer("❌ Режим ИИ выключен. Теперь твои сообщения снова отправляются админу.", reply_markup=get_user_kb())

@dp.callback_query(F.data == "grok_admin")
async def grok_admin_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🤖 Чтобы спросить нейросеть Grok, используй команду:\n<code>/grok твой вопрос</code>", parse_mode="HTML")

# --- ОСТАЛЬНЫЕ ЮЗЕРСКИЕ И АДМИНСКИЕ КОМАНДЫ ---
@dp.message(Command("panel"), F.from_user.id == ADMIN_ID)
async def panel_cmd(message: Message):
    await message.answer("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

@dp.message(Command("tracks_control"), F.from_user.id == ADMIN_ID)
async def tracks_control_cmd(message: Message):
    await message.answer(f"🎵 <b>Управление треками</b>\n\nВсего треков в базе: {len(tracks_db)}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить трек", callback_data="add_track")],
        [InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_tracks")]
    ]))

@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def broadcast_cmd(message: Message, state: FSMContext):
    await message.answer("📢 Отправь мне любое сообщение (текст, фото или файл), которое улетит абсолютно ВСЕМ юзерам:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(Command("chats"), F.from_user.id == ADMIN_ID)
async def chats_cmd(message: Message):
    if not recent_chats:
        await message.answer("Список недавних диалогов пока пуст!")
        return
    kb_buttons = [[InlineKeyboardButton(text=f"👤 {name}", callback_data=f"chat_with:{uid}")] for uid, name in recent_chats.items()]
    await message.answer("📝 <b>Выбери пользователя из недавних для отправки сообщения:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@dp.message(Command("tracks"))
async def user_tracks_cmd(message: Message):
    if not tracks_db:
        await message.answer("Пока нет доступных треков! Загляни позже.")
        return
    kb_list = [[InlineKeyboardButton(text=f"🎵 {t['name']}", callback_data=f"play:{i}")] for i, t in enumerate(tracks_db)]
    await message.answer("🔥 <b>Выбирай любой трек IvanFucken:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.message(Command("dice"))
async def user_dice_cmd(message: Message):
    chat_id = message.chat.id
    await message.answer("Ха, решил испытать удачу? Ну давай, кидаем кости! 👀")
    user_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    bot_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
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

# --- СИНХРОНИЗАЦИЯ КНОПОК С КОМАНДАМИ (CALLBACK HANDLERS) ---
@dp.callback_query(F.data == "list_tracks")
async def list_tracks_callback(callback: CallbackQuery):
    await callback.answer()
    await user_tracks_cmd(callback.message)

@dp.callback_query(F.data == "dice")
async def dice_callback(callback: CallbackQuery):
    await callback.answer()
    await user_dice_cmd(callback.message)

@dp.callback_query(F.data == "manage_tracks")
async def manage_tracks_callback(callback: CallbackQuery):
    await callback.answer()
    await tracks_control_cmd(callback.message)

@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await broadcast_cmd(callback.message, state)

@dp.callback_query(F.data == "recent_chats")
async def show_recent_cb(callback: CallbackQuery):
    await callback.answer()
    await chats_cmd(callback.message)

# --- ОСТАЛЬНАЯ ЛОГИКА АДМИНКИ И СЦЕНАРИИ ВВОДА ---
@dp.callback_query(F.data == "add_track")
async def add_track_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Пришли мне mp3-файл трека:")
    await state.set_state(AdminStates.waiting_for_track_file)

@dp.message(AdminStates.waiting_for_track_file, F.audio)
async def get_track_file(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id)
    await message.answer("Файл получен! Напиши его название:")
    await state.set_state(AdminStates.waiting_for_track_name)

@dp.message(AdminStates.waiting_for_track_name, F.text)
async def get_track_name(message: Message, state: FSMContext):
    data = await state.get_data()
    tracks_db.append({"name": message.text, "file_id": data['file_id']})
    await state.clear()
    await message.answer(f"✅ Трек «<b>{message.text}</b>» успешно добавлен!", parse_mode="HTML", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "clear_tracks")
async def clear_tracks(callback: CallbackQuery):
    await callback.answer()
    tracks_db.clear()
    await callback.message.edit_text("🗑 Все треки удалены.", reply_markup=get_admin_kb())

@dp.callback_query(F.data.startswith("play:"))
async def play_track(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    await callback.answer("Загружаю... 🎧")
    try:
        await bot.send_audio(callback.message.chat.id, tracks_db[idx]['file_id'], caption="Понравился трек? Качай и делись с кентами! 😎")
    except Exception as e:
        logger.error(f"Ошибка воспроизведения: {e}")

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    if not users:
        await message.answer("👥 База пуста.", reply_markup=get_admin_kb())
        return
    success = 0
    for uid in list(users.keys()):
        try:
            await message.send_copy(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"📊 Рассылка завершена! Доставлено: {success}", reply_markup=get_admin_kb())

@dp.callback_query(F.data.startswith("chat_with:"))
async def start_chat_with(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = int(callback.data.split(":")[1])
    name = recent_chats.get(uid, "Пользователь")
    await state.update_data(target_uid=uid)
    await callback.message.answer(f"🗣 Режим прямой отправки пользователю <b>{name}</b> (ID: {uid}).\n\nОтправь сообщение:", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.callback_query(F.data == "direct_send_start")
async def direct_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("👤 Введи цифровой Telegram ID:")
    await state.set_state(AdminStates.waiting_for_direct_uid)

@dp.message(AdminStates.waiting_for_direct_uid)
async def get_uid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ ID должен состоять только из цифр:")
        return
    uid = int(message.text)
    name = users.get(uid, f"Юзер {uid}")
    recent_chats[uid] = name
    await state.update_data(target_uid=uid)
    await message.answer(f"ID принят! Отправь сообщение для {name}:")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.message(AdminStates.waiting_for_direct_msg)
async def send_direct_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()
    try:
        await message.send_copy(chat_id=uid)
        await message.answer("✅ Сообщение доставлено!", reply_markup=get_admin_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "view_stats")
async def view_stats(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n👥 Уникальных юзеров: <b>{len(users)}</b>\n🎵 Треков в меню: <b>{len(tracks_db)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="back_admin")]])
    )

@dp.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

# --- ОТВЕТ АДМИНА ПО REPLY ---
@dp.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message):
    uid = forward_map.get(message.reply_to_message.message_id)
    if uid:
        try:
            recent_chats[uid] = users.get(uid, f"Юзер {uid}")
            await message.send_copy(chat_id=uid)
            await message.answer("✅ Ответ успешно отправлен пользователю.")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить ответ. Ошибка: {e}")
    else:
        await message.answer("⚠️ Бот не определил юзера по этому реплаю. Используй команду /chats для прямой отправки.")

# --- ОБРАБОТКА ТЕКСТА ЮЗЕРОВ (ИИ ИЛИ ПЕРЕСЫЛКА АДМИНУ) ---
# Хэндлер стоит в конце, чтобы не перехватывать команды и админ-действия
@dp.message(F.chat.id != ADMIN_ID)
async def chat_flow(message: Message):
    # Регистрируем
    users[message.from_user.id] = message.from_user.full_name
    recent_chats[message.from_user.id] = message.from_user.full_name
    
    # 1. Если у пользователя включен режим ИИ
    if message.from_user.id in ai_mode_users:
        if message.text:
            msg = await message.answer("🔄 Думаю...")
            reply = await ask_grok(message.text)
            await msg.edit_text(reply, reply_markup=get_exit_ai_kb())
        else:
            await message.answer("🤖 Я умею обрабатывать только текстовые вопросы.", reply_markup=get_exit_ai_kb())
        return

    # 2. Обычный режим (пересылка админу)
    user = message.from_user
    username_part = f"@{user.username}" if user.username else "(нет юзернейма)"
    header = f"📨 <b>От: {user.full_name}</b> {username_part}\nID: <code>{user.id}</code>\n\n"
    
    await bot.send_message(chat_id=ADMIN_ID, text=header, parse_mode="HTML")
    msg = await message.send_copy(chat_id=ADMIN_ID)
    forward_map[msg.message_id] = message.chat.id

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
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
