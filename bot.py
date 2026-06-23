Import asyncio
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
import aiohttp

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") # Сюда прилетит ключ из панели Render

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗЫ ДАННЫХ В ПАМЯТИ ---
users = {}          
tracks_db = []      
recent_chats = {}   
forward_map = {}    
ai_mode_users = set() 

# Хранилище контекста диалогов для Gemini
ai_history = {}  

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
        [InlineKeyboardButton(text="🤖 Спросить ИИ", callback_data="grok_admin"), InlineKeyboardButton(text="🎲 Кинуть кость", callback_data="dice")]
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
        BotCommand(command="grok", description="🤖 Быстрый вопрос к бесплатной нейросети"),
        BotCommand(command="dice", description="🎲 Кинуть кость")
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    if ADMIN_ID:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except Exception as e: pass

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await set_bot_commands()
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Привет, админ! Твоя panel управления готова.", reply_markup=get_admin_kb())
    else:
        users[message.from_user.id] = message.from_user.full_name
        recent_chats[message.from_user.id] = message.from_user.full_name
        await message.answer(
            "✌️ Здарова! Я новый бот. Можешь послушать мои треки, рискнуть сыграть со мной в кости или "
            "<b>пообщаться с искусственным интеллектом</b> абсолютно бесплатно!\n\n"
            "Используй кнопки ниже или команды в меню: /tracks, /grok и /dice.",
            parse_mode="HTML",
            reply_markup=get_user_kb()
        )

     # --- СТАБИЛЬНЫЙ ИИ (gemini-2.0-flash) ---
async def ask_free_ai(user_id: int, prompt: str) -> str:
    if not GEMINI_API_KEY: return "⚠️ Ключ не настроен!"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        if user_id not in ai_history: ai_history[user_id] = []
        ai_history[user_id].append({"role": "user", "parts": [{"text": prompt}]})
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"contents": ai_history[user_id]}, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    ai_history[user_id].append({"role": "model", "parts": [{"text": text}]})
                    return text
                return f"⚠️ Ошибка API ({resp.status})"
    except Exception as e:
        logger.error(f"ИИ Ошибка: {e}")
        return "⚠️ Ошибка связи с нейросетью."               
                
        # Системный промпт зашиваем прямо перед отправкой, чтобы модель знала роль
        system_instruction = "Ты крутой ИИ-ассистент IvanFuckenBot. Отвечай кратко, используй молодежный сленг, пиши только на русском и по делу."
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        
        payload = {
            "contents": ai_history[user_id],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 800
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20) as response:
                if response.status == 200:
                    result = await response.json()
                    try:
                        reply_text = result['candidates'][0]['content']['parts'][0]['text']
                        reply_text = reply_text.strip()
                        
                        if reply_text:
                            # Добавляем ответ модели в историю
                            ai_history[user_id].append({"role": "model", "parts": [{"text": reply_text}]})
                            
                            # Ограничиваем контекст (последние 10 реплик)
                            if len(ai_history[user_id]) > 10:
                                ai_history[user_id] = ai_history[user_id][-10:]
                            return reply_text
                    except KeyError:
                        pass
                else:
                    error_data = await response.text()
                    logger.error(f"Gemini API Error: {error_data}")

        return "⚠️ Нейросеть перегружена или думает слишком долго. Повтори вопрос."
        
    except Exception as e:
        logger.error(f"Ошибка Gemini: {e}")
        if user_id in ai_history and len(ai_history[user_id]) > 0:
            ai_history[user_id].pop()
        return "⚠️ Произошла ошибка при обращении к ИИ. Попробуй позже."

# --- КОМАНДЫ И CALLBACK ДЛЯ ИИ ---
@dp.message(Command("grok"))
async def grok_command(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        prompt = message.text.replace("/grok", "").strip()
        if not prompt:
            await message.answer("Использование для админа: <code>/grok твой вопрос</code>", parse_mode="HTML")
            return
        msg = await message.answer("🔄 Нейросеть думает...")
        reply = await ask_free_ai(message.from_user.id, prompt)
        await msg.edit_text(reply)
    else:
        ai_mode_users.add(message.from_user.id)
        await message.answer("🤖 <b>Режим общения с нейросетью активирован!</b>\n\nПиши мне любые вопросы, отвечу бесплатно и запомню контекст диалога.", parse_mode="HTML", reply_markup=get_exit_ai_kb())

@dp.callback_query(F.data == "grok_start")
async def grok_start_callback(callback: CallbackQuery):
    await callback.answer()
    ai_mode_users.add(callback.from_user.id)
    await callback.message.answer("🤖 <b>Режим общения с нейросетью активирован!</b>\n\nЗадавай свои вопросы:", parse_mode="HTML", reply_markup=get_exit_ai_kb())

@dp.callback_query(F.data == "grok_stop")
async def grok_stop_callback(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ai_mode_users:
        ai_mode_users.remove(callback.from_user.id)
    if callback.from_user.id in ai_history:
        del ai_history[callback.from_user.id]
    await callback.message.answer("❌ Режим ИИ выключен. Контекст диалога полностью сброшен.", reply_markup=get_user_kb())

@dp.callback_query(F.data == "grok_admin")
async def grok_admin_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🤖 Чтобы спросить нейросеть, используй команду:\n<code>/grok твой вопрос</code>", parse_mode="HTML")

# --- ОСТАЛЬНАЯ ЛОГИКА БОТА ---
@dp.message(Command("panel"), F.from_user.id == ADMIN_ID)
async def panel_cmd(message: Message):
    await message.answer("⚙️ Панель управления IvanFuckenBot:", reply_markup=get_admin_kb())

@dp.message(Command("tracks_control"), F.from_user.id == ADMIN_ID)
async def tracks_control_cmd(message: Message):
    await message.answer(f"🎵 <b>Управление треками</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить трек", callback_data="add_track")],
        [InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_tracks")]
    ]))

@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def broadcast_cmd(message: Message, state: FSMContext):
    await message.answer("📢 Отправь мне сообщение для рассылки ВСЕМ юзерам:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(Command("chats"), F.from_user.id == ADMIN_ID)
async def chats_cmd(message: Message):
    if not recent_chats:
        await message.answer("Список недавних диалогов пока пуст!")
        return
    kb_buttons = [[InlineKeyboardButton(text=f"👤 {name}", callback_data=f"chat_with:{uid}")] for uid, name in recent_chats.items()]
    await message.answer("📝 <b>Выбери пользователя:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@dp.message(Command("tracks"))
async def user_tracks_cmd(message: Message):
    if not tracks_db:
        await message.answer("Пока нет доступных треков!")
        return
    kb_list = [[InlineKeyboardButton(text=f"🎵 {t['name']}", callback_data=f"play:{i}")] for i, t in enumerate(tracks_db)]
    await message.answer("🔥 <b>Выбирай любой трек:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.message(Command("dice"))
async def user_dice_cmd(message: Message):
    chat_id = message.chat.id
    await message.answer("🎲 Кидаем кости...")
    user_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    bot_dice = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    await asyncio.sleep(4)
    u, b = user_dice.dice.value, bot_dice.dice.value
    result = "Ты выиграл! 😳" if u > b else ("ТЫ ПРОИГРАЛ! 🤭" if u < b else "Ничья! 🤔")
    await bot.send_message(chat_id=chat_id, text=f"Твой результат: {u} 🎰 Мой результат: {b}\n\n{result}")

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

@dp.callback_query(F.data == "add_track")
async def add_track_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Пришли mp3-файл трека:")
    await state.set_state(AdminStates.waiting_for_track_file)

@dp.message(AdminStates.waiting_for_track_file, F.audio)
async def get_track_file(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id)
    await message.answer("Напиши его название:")
    await state.set_state(AdminStates.waiting_for_track_name)

@dp.message(AdminStates.waiting_for_track_name, F.text)
async def get_track_name(message: Message, state: FSMContext):
    data = await state.get_data()
    tracks_db.append({"name": message.text, "file_id": data['file_id']})
    await state.clear()
    await message.answer(f"✅ Трек добавлен!", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "clear_tracks")
async def clear_tracks(callback: CallbackQuery):
    await callback.answer()
    tracks_db.clear()
    await callback.message.edit_text("🗑 Все треки удалены.", reply_markup=get_admin_kb())

@dp.callback_query(F.data.startswith("play:"))
async def play_track(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    await callback.answer()
    try:
        await bot.send_audio(callback.message.chat.id, tracks_db[idx]['file_id'])
    except: pass

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    success = 0
    for uid in list(users.keys()):
        try:
            await message.send_copy(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"📊 Доставлено: {success}", reply_markup=get_admin_kb())

@dp.callback_query(F.data.startswith("chat_with:"))
async def start_chat_with(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = int(callback.data.split(":")[1])
    await state.update_data(target_uid=uid)
    await callback.message.answer(f"🗣 Режим прямой отправки пользователю {uid}. Отправь сообщение:")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.callback_query(F.data == "direct_send_start")
async def direct_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("👤 Введи цифровой Telegram ID:")
    await state.set_state(AdminStates.waiting_for_direct_uid)

@dp.message(AdminStates.waiting_for_direct_uid)
async def get_uid(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    uid = int(message.text)
    await state.update_data(target_uid=uid)
    await message.answer(f"ID принят! Отправь сообщение для {uid}:")
    await state.set_state(AdminStates.waiting_for_direct_msg)

@dp.message(AdminStates.waiting_for_direct_msg)
async def send_direct_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()
    try:
        await message.send_copy(chat_id=uid)
        await message.answer("✅ Доставлено!", reply_markup=get_admin_kb())
    except: pass

@dp.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message):
    uid = forward_map.get(message.reply_to_message.message_id)
    if uid:
        try:
            await message.send_copy(chat_id=uid)
            await message.answer("✅ Ответ отправлен.")
        except: pass

@dp.message(F.chat.id != ADMIN_ID)
async def chat_flow(message: Message):
    users[message.from_user.id] = message.from_user.full_name
    recent_chats[message.from_user.id] = message.from_user.full_name
    
    if message.from_user.id in ai_mode_users:
        if message.text:
            msg = await message.answer("🔄 Думаю...")
            reply = await ask_free_ai(message.from_user.id, message.text)
            await msg.edit_text(reply, reply_markup=get_exit_ai_kb())
        return

    header = f"📨 <b>От: {message.from_user.full_name}</b>\nID: <code>{message.from_user.id}</code>\n\n"
    await bot.send_message(chat_id=ADMIN_ID, text=header, parse_mode="HTML")
    msg = await message.send_copy(chat_id=ADMIN_ID)
    forward_map[msg.message_id] = message.chat.id

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


Вот этот код перепиши чтобы нейросеть работала. Например на Gemini 2.5 flash
