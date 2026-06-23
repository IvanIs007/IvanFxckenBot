import os
import sys
import asyncio
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web, ClientSession

# ==============================================================================
# 1. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ И АДМИНИСТРАТОРА
# ==============================================================================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")  
PORT = int(os.environ.get("PORT", 10000))

# Жестко прописываем твой ID в код, чтобы исключить сбои с Environment в Render
ADMIN_ID = 509023958  

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь токены в Render!")
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

# АКТУАЛИЗИРОВАННЫЙ СПИСОК ЖЕЛЕЗОБЕТОННЫХ БЕСПЛАТНЫХ МОДЕЙ OPENROUTER
MODELS_DATABASE = {
    "openrouter/free": "🤖 Автовыбор ИИ (Самая быстрая свободная)",
    "meta-llama/llama-3-8b-instruct:free": "🦙 Llama 3 8B (Free)",
    "qwen/qwen-2-7b-instruct:free": "🐉 Qwen 2 7B (Free)",
    "microsoft/phi-3-mini-128k-instruct:free": "🧩 Phi-3 Mini (Free)"
}

# ==============================================================================
# 2. РАБОТА С БАЗОЙ ДАННЫХ
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
# 3. ГЕНЕРАЦИЯ КЛАВИАТУР
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

def get_models_inline_keyboard():
    builder = InlineKeyboardBuilder()
    for model_id, name in MODELS_DATABASE.items():
        # Превращаем ID в короткий уникальный callback-ключ
        short_id = model_id.split("/")[-1].split(":")[0][:15]
        builder.button(text=name, callback_data=f"set_{short_id}")
    builder.adjust(1)
    return builder.as_markup()

# ==============================================================================
# 4. ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ И ИГРЫ
# ==============================================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)  
    await message.answer(
        "✌️ Здорова! Я обновленный бот.\nВыбирай действия на кнопках ниже!",
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
    await message.answer("Выберите бесплатную модель из списка стабильных:", reply_markup=get_models_inline_keyboard())

@dp.callback_query(F.data.startswith("set_"))
async def process_set_model(callback: types.CallbackQuery, state: FSMContext):
    short_id = callback.data.split("_")[1]
    full_model_id = "openrouter/free"
    
    for m_id in MODELS_DATABASE.keys():
        if short_id in m_id:
            full_model_id = m_id
            break
            
    await state.update_data(current_model=full_model_id)
    model_name = MODELS_DATABASE[full_model_id]
    
    await callback.message.edit_text(f"✅ Модель успешно изменена на:\n**{model_name}**\n\nЖду твоих вопросов!")
    await callback.answer()

@dp.message(BotStates.ai_mode, F.text == "❌ Выйти из режима ИИ")
async def exit_ai_mode(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из режима ИИ.", reply_markup=get_main_keyboard())

@dp.message(F.text == "🎧 Послушать треки")
async def handle_tracks(message: types.Message):
    await message.answer("🎵 Тут когда-нибудь будут треки...")

@dp.message(F.text == "🎲 Сыграть в кости")
async def handle_dice(message: types.Message):
    await message.answer("🎲 Играем! Сначала кидаю я, потом ты...")
    
    bot_msg = await message.answer_dice()
    bot_score = bot_msg.dice.value
    await asyncio.sleep(4) 
    
    user_msg = await message.answer_dice()
    user_score = user_msg.dice.value
    await asyncio.sleep(4)
    
    result_text = f"🤖 Мой результат: **{bot_score}**\n👤 Твой результат: **{user_score}**\n\n"
    
    if bot_score > user_score:
        result_text += random.choice([
            "Ха! Я победил! Слава роботам! 🤖🦾",
            "Изи вин для искусственного интеллекта! 😎",
            "Удача сегодня на моей стороне! 😉"
        ])
    elif user_score > bot_score:
        result_text += random.choice([
            "Ого! Ты выиграл! Признавайся, подкрутил кубики? 🧐🎉",
            "Поздравляю, твоя удача сильнее алгоритмов! 🏆",
            "Ты победил! Чистая победа человека! ✊"
        ])
    else:
        result_text += random.choice([
            "Ничья! Мы достойные соперники друг друга 🤝",
            "На кубиках одинаково! Давай перекинем? 🔄"
        ])
        
    await message.answer(result_text, parse_mode="Markdown")

# ==============================================================================
# 5. ГАРАНТИРОВАННО РАБОЧАЯ ПАНЕЛЬ АДМИНИСТРАТОРА
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return  
    await message.answer("🔑 Панель администратора открыта, Босс!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Вышли из панели управления.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    count = get_users_count()
    await message.answer(f"📊 **Статистика бота:**\n\nВсего уникальных пользователей: `{count}`", parse_mode="Markdown")

# --- СЦЕНАРИЙ ОБЩЕЙ РАССЫЛКИ ---
@dp.message(F.text == "📢 Рассылка всем")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("Введите текст для рассылки всем пользователям:", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_exec(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())
        return
        
    users = get_all_users()
    success, failed = 0, 0
    await message.answer(f"⏳ Начинаю рассылку...")
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=int(user_id), text=message.text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
            
    await state.clear()
    await message.answer(f"📢 **Рассылка завершена!**\n\nУспешно: `{success}`\nНе дошло: `{failed}`", 
                         reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# --- СЦЕНАРИЙ ЛИЧНОГО СООБЩЕНИЯ ---
@dp.message(F.text == "👤 Личное сообщение")
async def admin_private_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_private_id)
    await message.answer("Пришлите Telegram ID пользователя:", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))

@dp.message(BotStates.admin_private_id)
async def admin_private_get_id(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
    if not message.text.isdigit():
        await message.answer("ID должен состоять только из цифр. Попробуйте еще раз:")
        return
        
    await state.update_data(target_user_id=message.text)
    await state.set_state(BotStates.admin_private_msg)
    await message.answer(f"ID {message.text} принят. Введите сообщение для отправки:")

@dp.message(BotStates.admin_private_msg)
async def admin_private_send(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_admin_keyboard())
        return
        
    data = await state.get_data()
    target_id = int(data.get("target_user_id"))
    
    try:
        await bot.send_message(chat_id=target_id, text=f"✉️ **Сообщение от администрации:**\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Сообщение успешно отправлено!")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить. Ошибка: {e}")
        
    await state.clear()
    await message.answer("Возвращаю меню админки.", reply_markup=get_admin_keyboard())

# ==============================================================================
# 6. ВЗАИМОДЕЙСТВИЕ С OPENROUTER
# ==============================================================================
@dp.message(BotStates.ai_mode)
async def handle_ai_request(message: types.Message, state: FSMContext):
    if not message.text or message.text in ["❌ Выйти из режима ИИ", "⚙️ Выбрать нейросеть"]: return 
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    user_data = await state.get_data()
    chosen_model = user_data.get("current_model", "openrouter/free")
    
    payload = {
        "model": chosen_model, 
        "messages": [{"role": "user", "content": message.text}]
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://render.com", 
        "X-Title": "Telegram Bot" 
    }

    try:
        async with ClientSession() as session:
            async with session.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=50) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        ai_text = data['choices'][0]['message']['content']
                        await message.answer(ai_text)
                    else:
                        await message.answer("⚠️ Нейросеть вернула пустой ответ. Смените модель.")
                else:
                    await message.answer(f"⚠️ Ошибка OpenRouter (Код {response.status}). Попробуйте сменить модель.")
    except Exception:
        await message.answer("⚠️ Ошибка сети. Попробуйте еще раз.")

# ==============================================================================
# 7. ЗАПУСК
# ==============================================================================
async def handle_render_ping(request):
    return web.Response(text="Бот онлайн!", status=200)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_render_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host='0.0.0.0', port=PORT).start()

    print("Запуск бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
