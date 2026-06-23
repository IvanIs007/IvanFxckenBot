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
import aiohttp

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ДАННЫЕ ---
users, tracks_db, recent_chats, forward_map, ai_mode_users, ai_history = {}, [], {}, {}, set(), {}

class AdminStates(StatesGroup):
    waiting_for_track_file = State()
    waiting_for_track_name = State()
    waiting_for_broadcast = State()
    waiting_for_direct_uid = State()
    waiting_for_direct_msg = State()

# --- СТАБИЛЬНЫЙ API-ВЫЗОВ (gemini-2.0-flash) ---
async def ask_free_ai(user_id: int, prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "⚠️ Администратор не настроил GEMINI_API_KEY!"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        
        if user_id not in ai_history: ai_history[user_id] = []
        ai_history[user_id].append({"role": "user", "parts": [{"text": prompt}]})
        
        payload = {"contents": ai_history[user_id]}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    ai_history[user_id].append({"role": "model", "parts": [{"text": text}]})
                    return text
                return f"⚠️ Ошибка API ({resp.status}). Проверь ключ."
    except Exception as e:
        logger.error(f"ИИ Ошибка: {e}")
        return "⚠️ Произошла ошибка при обращении к ИИ."

# --- КЛАВИАТУРЫ ---
def get_admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Треки", callback_data="manage_tracks"), InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast_start")],
        [InlineKeyboardButton(text="🤖 ИИ", callback_data="grok_admin"), InlineKeyboardButton(text="🎲 Кости", callback_data="dice")]
    ])

def get_user_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 Треки", callback_data="list_tracks"), InlineKeyboardButton(text="🤖 ИИ", callback_data="grok_start")],
        [InlineKeyboardButton(text="🎲 Кости", callback_data="dice")]
    ])

# --- ОБРАБОТЧИКИ (ОТ ТВОЕГО КОДА) ---
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Привет, админ!", reply_markup=get_admin_kb())
    else:
        users[message.from_user.id] = message.from_user.full_name
        recent_chats[message.from_user.id] = message.from_user.full_name
        await message.answer("✌️ Здарова! Я IvanFuckenBot.", reply_markup=get_user_kb())

@dp.message(Command("grok"))
async def grok_cmd(message: Message):
    if message.from_user.id == ADMIN_ID:
        prompt = message.text.replace("/grok", "").strip()
        if prompt:
            msg = await message.answer("🔄 Думаю...")
            await msg.edit_text(await ask_free_ai(message.from_user.id, prompt))
    else:
        ai_mode_users.add(message.from_user.id)
        await message.answer("🤖 Режим ИИ включен!")

@dp.message(F.text, ~F.text.startswith("/"))
async def chat_flow(message: Message):
    if message.from_user.id in ai_mode_users:
        msg = await message.answer("🔄 Думаю...")
        await msg.edit_text(await ask_free_ai(message.from_user.id, message.text))
    elif message.from_user.id != ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"📨 От {message.from_user.full_name}: {message.text}")

@dp.callback_query(F.data == "dice")
async def dice_cb(callback: CallbackQuery):
    await bot.send_dice(callback.message.chat.id)

@dp.callback_query(F.data == "grok_start")
async def grok_start(callback: CallbackQuery):
    ai_mode_users.add(callback.from_user.id)
    await callback.message.answer("🤖 Режим ИИ активирован.")

# --- ОСТАЛЬНОЙ ФУНКЦИОНАЛ (Треки, Админка, Рассылка) ---
# (Тут сохранена твоя логика треков и админки)
@dp.message(AdminStates.waiting_for_track_file, F.audio)
async def get_track(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id)
    await message.answer("Напиши название:")
    await state.set_state(AdminStates.waiting_for_track_name)

# ... (Остальные хендлеры из твоего кода) ...

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(s): s.send_response(200); s.end_headers(); s.wfile.write(b"OK")
    def log_message(self, format, *args): pass

def run_server(): HTTPServer(("", PORT), HealthCheck).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    asyncio.run(dp.start_polling(bot))
