import os
import sys
import asyncio
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web, ClientSession, ClientTimeout

# ==============================================================================
# 1. СЧИТЫВАНИЕ НАСТРОЕК ИЗ RENDER ENVIRONMENT
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))

# Получаем данные админа из Render
ENV_ADMIN_ID = os.environ.get("ADMIN_ID", "")
ENV_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").replace("@", "").strip().lower()

try:
    ADMIN_ID = int(ENV_ADMIN_ID) if ENV_ADMIN_ID.isdigit() else 0
except ValueError:
    ADMIN_ID = 0

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в Render!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

USERS_FILE = "users.txt"

class BotStates(StatesGroup):
    ai_mode = State()         
    admin_broadcast = State() 
    admin_private_id = State()
    admin_private_msg = State()

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# ПОЛНАЯ АКТУАЛЬНАЯ БАЗА БЕСПЛАТНЫХ МОДЕЛЕЙ OPENROUTER
MODELS_DATABASE = {
    "openrouter/free": "🤖 Автовыбор OpenRouter",
    "openrouter/owl-alpha": "🦉 Owl Alpha (Agentic)",
    "nvidia/nemotron-3-ultra:free": "⚡ Nemotron 3 Ultra",
    "poolside/laguna-m1:free": "🌊 Poolside Laguna M.1",
    "nvidia/nemotron-3-super:free": "💥 Nemotron 3 Super",
    "openai/gpt-oss-120b:free": "🌌 OpenAI gpt-oss-120b",
    "poolside/laguna-xs2:free": "🏖 Poolside Laguna XS.2",
    "openai/gpt-oss-20b:free": "🌠 OpenAI gpt-oss-20b",
    "google/gemma-4-31b:free": "🧠 Google Gemma 4 31B",
    "nvidia/nemotron-3-nano-30b-a3b:free": "📟 Nemotron 3 Nano 30B",
    "cohere/north-mini-code:free": "💻 Cohere North Mini Code",
    "nvidia/nemotron-3-nano-omni:free": "👁 Nemotron 3 Nano Omni",
    "nvidia/nemotron-nano-9b-v2:free": "📲 Nemotron Nano 9B v2",
    "nvidia/nemotron-nano-12b-2-vl:free": "🎬 Nemotron Nano 12B VL",
    "nvidia/llama-nemotron-embed-vl-1b-v2:free": "🗂 Llama Embed VL 1B",
    "google/gemma-4-26b-a4b:free": "🧬 Google Gemma 4 26B"
}

# Функция проверки прав администратора (сверяет ID ИЛИ Username)
def is_admin(user: types.User) -> bool:
    if ADMIN_ID > 0 and user.id == ADMIN_ID:
        return True
    if ENV_ADMIN_USERNAME and user.username and user.username.lower() == ENV_ADMIN_USERNAME:
        return True
    return False

# ==============================================================================
# 2. РАБОТА С ФАЙЛОМ ПОЛЬЗОВАТЕЛЕЙ
# ==============================================================================
def save_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f: f.write(f"{user_id}\n")
        return
    with open(USERS_FILE, "r") as f: users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f: f.write(f"{user_id}\n")

def get_users_count() -> int:
    if not os.path.exists(USERS_FILE): return 0
    with open(USERS_FILE, "r") as f: return len(f.read().splitlines())

def get_all_users() -> list:
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return f.read().splitlines()

# ==============================================================================
# 3. КЛАВИАТУРЫ
# ==============================================================================
def get_main_keyboard():
    buttons = [
        [types.KeyboardButton(text="🎧 Послушать треки"), types.KeyboardButton(text="🤖 Общение с ИИ")],
        [types.KeyboardButton(text="🎲 Сыграть в кости")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_ai_keyboard():
    buttons = [
        [types.KeyboardButton(text="⚙️ Выбрать нейросеть")],
        [types.KeyboardButton(text="❌ Выйти из режима ИИ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка всем")],
        [types.KeyboardButton(text="👤 Личное сообщение"), types.KeyboardButton(text="🚪 Выйти из админки")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_models_inline_keyboard(page: int = 0):
    builder = InlineKeyboardBuilder()
    items = list(MODELS_DATABASE.items())
    per_page = 5  
    start = page * per_page
    end = start + per_page
    
    for model_id, name in items[start:end]:
        short_id = model_id.replace("free", "").replace("/", "-")[:20]
        builder.button(text=name, callback_data=f"set_{short_id}_{page}")
    
    builder.adjust(1)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{page-1}"))
    if end < len(items):
        nav_buttons.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
        
    return builder.as_markup()

# ==============================================================================
# 4. ХЕНДЛЕРЫ КЛИЕНТСКОЙ ЧАСТИ И ИГРЫ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)  
    await message.answer(
        "✌️ Привет! Код успешно обновлен, таймауты Deep Search исправлены.\nВыбирай действия на кнопках ниже!",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("ai"))
@dp.message(F.text == "🤖 Общение с ИИ")
async def start_ai_mode(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_mode)
    data = await state.get_data()
    current_model = data.get("current_model", "openrouter/free")
    model_name = MODELS_DATABASE.get(current_model, "Автовыбор")
    
    await message.answer(
        f"🤖 **Режим ИИ активирован!**\nТекущая модель: `{model_name}`\n\nЗадай свой вопрос:",
        reply_markup=get_ai_keyboard(), parse_mode="Markdown"
    )

@dp.message(BotStates.ai_mode, F.text == "⚙️ Выбрать нейросеть")
async def show_models_menu(message: types.Message):
    await message.answer("Выберите бесплатную нейросеть:", reply_markup=get_models_inline_keyboard(0))

@dp.callback_query(F.data.startswith("page_"))
async def process_model_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_models_inline_keyboard(page))
    await callback.answer()

@dp.callback_query(F.data.startswith("set_"))
async def process_set_model(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    target_short = parts[1]
    
    full_model_id = "openrouter/free"
    for m_id in MODELS_DATABASE.keys():
        check_str = m_id.replace("free", "").replace("/", "-")[:20]
        if check_str == target_short:
            full_model_id = m_id
            break
            
    await state.update_data(current_model=full_model_id)
    model_name = MODELS_DATABASE[full_model_id]
    
    await callback.message.edit_text(f"✅ Установлена модель:\n**{model_name}**\n\nЗадавайте ваш вопрос!")
    await callback.answer()

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎧 Послушать треки")
async def handle_tracks(message: types.Message):
    await message.answer("🎵 Раздел аудиозаписей находится в разработке.")

@dp.message(F.text == "🎲 Сыграть в кости")
async def handle_dice(message: types.Message):
    await message.answer("🎲 Игра началась! Мой бросок:")
    bot_msg = await message.answer_dice()
    bot_score = bot_msg.dice.value
    await asyncio.sleep(4) 
    
    await message.answer("🎲 Теперь твой бросок:")
    user_msg = await message.answer_dice()
    user_score = user_msg.dice.value
    await asyncio.sleep(4)
    
    result_text = f"🤖 Мои очки: **{bot_score}**\n👤 Твои очки: **{user_score}**\n\n"
    if bot_score > user_score:
        result_text += random.choice(["Ха! Я победил! Слава роботам! 🤖🦾", "Изи вин для ИИ! 😎"])
    elif user_score > bot_score:
        result_text += random.choice(["Ого, ты победил! Подкрутил кубики? 🧐🎉", "Чистая победа человека над машиной! ✊"])
    else:
        result_text += "Ничья! Мы достойные соперники друг друга. 🤝"
        
    await message.answer(result_text, parse_mode="Markdown")

# ==============================================================================
# 5. ИСПРАВЛЕННАЯ АДМИН-ПАНЕЛЬ (ДИНАМИЧЕСКАЯ ИЗ ENV)
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user):
        return  # Обычные пользователи просто игнорируются
    await message.answer("🔑 Панель администратора успешно инициализирована из Render!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message):
    if not is_admin(message.from_user): return
    await message.answer("Вы вышли из админ-панели.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user): return
    count = get_users_count()
    await message.answer(f"📊 **Статистика бота:**\n\nВсего пользователей в базе: `{count}`", parse_mode="Markdown")

@dp.message(F.text == "📢 Рассылка всем")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user): return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("Введите текст рассылки для всех:", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())
        return
        
    users = get_all_users()
    success, failed = 0, 0
    await message.answer("⏳ Рассылка запущена...")
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
            
    await state.clear()
    await message.answer(f"📢 **Итоги рассылки:**\n\nДоставлено: `{success}`\nНе дошло: `{failed}`", 
                         reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "👤 Личное сообщение")
async def admin_private_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user): return
    await state.set_state(BotStates.admin_private_id)
    await message.answer("Введите числовой Telegram ID пользователя:", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_private_id)
async def admin_private_get_id(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
    if not message.text.isdigit():
        await message.answer("ID должен состоять только из цифр. Повторите ввод:")
        return
        
    await state.update_data(target_user_id=message.text)
    await state.set_state(BotStates.admin_private_msg)
    await message.answer(f"ID {message.text} сохранен. Теперь напишите текст сообщения:")

@dp.message(BotStates.admin_private_msg)
async def admin_private_send(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
        
    data = await state.get_data()
    target_id = int(data.get("target_user_id"))
    
    try:
        await bot.send_message(chat_id=target_id, text=f"✉️ **Сообщение от администратора:**\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Письмо успешно доставлено адресату!")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить. Ошибка: {e}")
        
    await state.clear()
    await message.answer("Возврат в меню администратора.", reply_markup=get_admin_keyboard())

# ==============================================================================
# 6. ОПТИМИЗИРОВАННЫЙ ИИ ОБРАБОТЧИК ЗАПРОСОВ (ПОТОКОВЫЙ СТРИМИНГ ДЛЯ DEEP SEARCH)
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message, state: FSMContext):
    if not message.text or message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return 
    
    # Отправляем статус "печать", создаем базовое сообщение для стриминга
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    status_msg = await message.answer("🧠 *Нейросеть генерирует ответ (Deep Search)...*", parse_mode="Markdown")
    
    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    payload = {
        "model": chosen_model, 
        "messages": [{"role": "user", "content": message.text}],
        "stream": True  # АКТИВИРУЕМ СТРИМИНГ ДЛЯ ИЗБЕЖАНИЯ СЕТЕВЫХ ТАЙМАУТОВ
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://render.com", 
        "X-Title": "Telegram Multibot" 
    }

    full_response = ""
    last_ui_update_text = ""
    counter = 0

    # Увеличиваем таймаут клиента до бесконечности, так как мы читаем чанки порциями
    timeout = ClientTimeout(total=None, connect=30, sock_read=300)

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers) as response:
                if response.status != 200:
                    await status_msg.edit_text(f"⚠️ Ошибка OpenRouter ({response.status}). Смените модель.")
                    return

                # Читаем потоковые данные линия за линией
                async for line in response.content:
                    if not line:
                        continue
                    
                    decoded_line = line.decode('utf-8').strip()
                    if not decoded_line.startswith("data:"):
                        continue
                    
                    cleaned_line = decoded_line[5:].strip()
                    if cleaned_line == "[DONE]":
                        break
                        
                    try:
                        chunk_data = json.loads(cleaned_line)
                        if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                            delta = chunk_data['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            full_response += content
                            counter += 1
                            
                            # Каждые 35 чанков обновляем текст на экране у пользователя, чтобы не спамить Telegram API
                            if counter % 35 == 0 and full_response.strip() != last_ui_update_text:
                                last_ui_update_text = full_response.strip()
                                # Отрезаем, если текст слишком длинный для одного сообщения в процессе
                                try:
                                    await status_msg.edit_text(last_ui_update_text[:4000])
                                except Exception:
                                    pass  # Игнорируем частые ошибки изменения UI
                    except Exception:
                        continue

        # Финальный вывод готового полного текста
        if full_response.strip():
            if len(full_response) <= 4096:
                await status_msg.edit_text(full_response)
            else:
                # Разбивка, если текст превысил лимит одного сообщения Telegram
                await status_msg.delete()
                for x in range(0, len(full_response), 4096):
                    await message.answer(full_response[x:x+4096])
        else:
            await status_msg.edit_text("⚠️ Ошибка: модель не вернула текстовых данных. Попробуйте другую.")
            
    except Exception as e:
        print(f"Исключение при стриминге: {e}")
        await status_msg.edit_text("⚠️ Ошибка сети OpenRouter при глубоком поиске. Попробуйте еще раз.")

# ==============================================================================
# 7. WEB SERVER RUNNER
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот активен!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
