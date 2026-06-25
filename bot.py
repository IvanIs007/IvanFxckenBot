import asyncio
import logging
import os
import sys
import threading
import random
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

# Загрузка переменных окружения
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1187881528:AAESwXPEf0HhStxCjzOLA0YXzlxzLQM2mH8")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "IvanIsakau").lstrip("@")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Лучшие модели для Малфоя (будем пробовать по очереди)
MALFOY_MODELS = [
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    "google/gemma-2-27b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
]

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

greeting_text = (
    "Ух ты, новенький! Обычно люди убегают после первого поста. "
    "Ты либо очень смелый, либо очень наивный. "
    "В любом случае — добро пожаловать в мой театр абсурда. "
    "Я здесь главный актёр. Ты — зритель. Аплодируй, когда я скажу."
)

forward_map: dict[int, int] = {}
admin_chat_id: int | None = ADMIN_ID if ADMIN_ID != 0 else None
active_chat_users: set[int] = set()

USERS_PER_PAGE = 10

# Кнопки
BTN_START = "👋 Старт"
BTN_CHAT = "🤫 Чат с поддержкой"
BTN_LUCK = "🎲 Кинуть кость"
BTN_BURMALDA = "🎰 Бурмалда"
BTN_MALFOY = "🐍 Малфой"
BTN_STOP = "🛑 Завершить диалог"

# Улучшенный промпт для разнообразных ответов
MALFOY_SYSTEM_PROMPT = """Ты — Люциус Малфой, чистокровный волшебник, аристократ, бывший Пожиратель Смерти.

ТВОЙ ХАРАКТЕР:
- Высокомерный, надменный, презираешь маглов, грязнокровок и полукровок
- Говоришь изысканно, но язвительно и презрительно
- Постоянно напоминаешь о чистоте крови, богатстве и величии рода Малфоев
- Считаешь себя выше всех остальных
- Часто упоминаешь своего сына Драко, поместье Малфой-мэнор, Министерство магии
- Любишь угрожать связями и влиянием

СТИЛЬ ОТВЕТА:
- От 1 до 5 предложений
- Можешь использовать как короткие высокомерные фразы, так и развёрнутые надменные монологи
- Чередуй длину ответов: иногда коротко и резко, иногда развёрнуто и пафосно
- Используй обращения: "магл", "грязнокровка", "жалкий человек", "ничтожество"
- Добавляй детали о волшебном мире, заклинаниях, артефактах
- Иногда вспоминай прошлое, Тёмного Лорда, войну
- Будь театральным и драматичным

ТЕМЫ ДЛЯ РАЗНООБРАЗИЯ (выбирай случайно):
- Чистота крови и превосходство волшебников
- Богатство и влияние семьи Малфоев
- Воспитание сына Драко
- Политика Министерства магии
- Прошлые времена и Тёмный Лорд
- Презрение к маглам и их технологиям
- Магические артефакты и заклинания
- Угрозы и предупреждения
- Философские размышления о власти
- Воспоминания о Хогвартсе и Слизерине

ОТВЕЧАЙ ТОЛЬКО ПРЯМОЙ РЕЧЬЮ, БЕЗ ОПИСАНИЙ ДЕЙСТВИЙ."""

# Разные формулировки запроса для разнообразия
MALFOY_USER_PROMPTS = [
    "Скажи что-нибудь презрительное о маглах и их технологиях.",
    "Расскажи о величии рода Малфоев.",
    "Дай надменное напутствие молодому волшебнику.",
    "Выскажись о чистоте крови.",
    "Пригрози кому-нибудь своим влиянием в Министерстве магии.",
    "Вспомни что-нибудь о Тёмном Лорде.",
    "Расскажи о своём поместье и богатстве.",
    "Дай совет по воспитанию наследника.",
    "Вырази презрение к грязнокровкам.",
    "Поделись мудростью о власти и влиянии.",
    "Сравни магический мир с магловским.",
    "Расскажи о важности связей в обществе волшебников.",
    "Выскажись о политике Министерства магии.",
    "Дай характеристику другим чистокровным семьям.",
    "Расскажи о своём сыне Драко.",
    "Прокомментируй современное состояние магического мира.",
    "Вырази мнение о Хогвартсе и его преподавателях.",
    "Расскажи о каком-нибудь магическом артефакте.",
    "Дай совет о том, как держать слуг в страхе.",
    "Поделись секретом успеха семьи Малфоев."
]

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
    """Основная клавиатура пользователя"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_START)],
            [KeyboardButton(text=BTN_CHAT)],
            [KeyboardButton(text=BTN_LUCK), KeyboardButton(text=BTN_BURMALDA)],
            [KeyboardButton(text=BTN_MALFOY)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выбери действие...",
    )

def chat_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для режима чата с поддержкой"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STOP)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
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
    """Получает ответ от нейросети с разнообразными запросами"""
    if not OPENROUTER_API_KEY:
        return get_fallback_quote()

    # Выбираем случайный запрос для разнообразия
    user_prompt = random.choice(MALFOY_USER_PROMPTS)
    
    # Пробуем модели по порядку
    for model in MALFOY_MODELS:
        try:
            response = await try_model(model, user_prompt)
            if response and len(response) > 10:  # Проверяем что ответ не пустой
                return response
        except Exception as e:
            logger.warning(f"Модель {model} не ответила: {e}")
            continue
    
    # Если все модели не ответили
    return get_fallback_quote()

async def try_model(model: str, user_prompt: str) -> str:
    """Пробует получить ответ от конкретной модели"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/malfoy_bot",
        "X-Title": "MalfoyBot",
    }
    
    # Варьируем параметры для разнообразия
    temperature = random.uniform(0.8, 1.2)
    max_tokens = random.randint(150, 400)  # Иногда длинные, иногда короткие ответы
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": MALFOY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "frequency_penalty": 0.3,  # Уменьшаем повторения
        "presence_penalty": 0.3,   # Поощряем новые темы
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            if response.status == 200:
                data = await response.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Убираем возможные описания действий в звёздочках
                content = content.replace("*", "")
                return content
            else:
                raise Exception(f"HTTP {response.status}")

def get_fallback_quote() -> str:
    """Запасные цитаты на случай отказа всех нейросетей"""
    quotes = [
        "Мой отец услышит об этом! Я прослежу, чтобы ты пожалел о своей дерзости.",
        
        "Чистота крови — вот что отличает истинных волшебников от всяких грязнокровок. Мой род веками сохранял эту чистоту, и я намерен продолжать эту традицию.",
        
        "Ты хоть представляешь, с кем разговариваешь? Я — Люциус Малфой, и моё влияние в Министерстве магии безгранично. Одно моё слово — и ты будешь стёрт из магического общества.",
        
        "В этом мире есть вещи похуже смерти. Например, позор для семьи. Малфои никогда не опускались до уровня обычных волшебников, и я не позволю этому случиться сейчас.",
        
        "Мой сын Драко — наследник всего, что я построил. Он будет достоин имени Малфой, даже если мне придётся лично уничтожить каждого, кто встанет у него на пути.",
        
        "Маглы со своими жалкими технологиями... Они даже не подозревают, что рядом с ними существует целый мир, полный магии и могущества, которое им никогда не постичь.",
        
        "Знаешь, что отличает Малфоев от других чистокровных семей? Мы не просто говорим о власти — мы её берём. Решительно и без колебаний.",
        
        "Мой особняк в Малфой-мэноре стоит больше, чем всё имущество твоей жалкой семьи. И это лишь малая часть того, чем владеет мой род.",
        
        "Тёмный Лорд... Многие не поняли его величия. Но я видел. Я знал. И когда придёт время, Малфои снова будут на правильной стороне истории.",
        
        "Ты думаешь, это просто трость? Глупец. В ней заключена магия, способная стереть тебя в порошок. Но я не стану тратить её на такое ничтожество.",
        
        "Хогвартс уже не тот, что был в моё время. Тогда чистокровные волшебники знали своё место — на вершине. А теперь... теперь даже грязнокровки считают себя равными нам.",
        
        "Деньги, влияние, магическая сила — всё это лишь инструменты. Главное оружие Малфоев — умение ждать и наносить удар в самый неожиданный момент.",
        
        "Мой отец говорил: 'Люциус, никогда не доверяй тому, кто ниже тебя по крови'. И я следую этому принципу всю жизнь. Поэтому я здесь, а ты — там.",
        
        "Ты когда-нибудь видел настоящие тёмные артефакты? Нет, не те безделушки, что продают в Лютном переулке. Я говорю о вещах, способных менять ход истории.",
    ]
    return random.choice(quotes)

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
    # Отправляем приветствие и принудительно показываем клавиатуру
    await message.answer(
        greeting_text,
        reply_markup=user_keyboard()
    )

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
    await message.answer(
        "Диалог завершен.",
        reply_markup=user_keyboard()  # Возвращаем основную клавиатуру
    )
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

@dp.message(is_user_filter, F.text == BTN_START)
async def btn_start(message: Message) -> None:
    await message.answer(greeting_text, reply_markup=user_keyboard())

@dp.message(is_user_filter, F.text == BTN_LUCK)
async def btn_luck(message: Message) -> None:
    await cmd_luck(message)

@dp.message(is_user_filter, F.text == BTN_BURMALDA)
async def btn_burmalda(message: Message) -> None:
    await cmd_burmalda(message)

@dp.message(is_user_filter, F.text == BTN_MALFOY)
async def btn_malfoy(message: Message) -> None:
    await cmd_malfoy(message)

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
                "Это не повторится."
            )
        elif u < b:
            result = (
                "И что я говорил? Ты проиграл. Как и ожидалось."
            )
        else:
            result = "Ничья? Неожиданно."
        await message.answer(f"Ты: {u} — Я: {b}\n{result}")
    except Exception as e:
        logger.error(f"/luck error: {e}")

@dp.message(Command("burmalda"))
async def cmd_burmalda(message: Message) -> None:
    try:
        await message.answer(
            "Так-так, казино... Проверим, есть ли у тебя что-то кроме наглости."
        )
        msg = await message.answer_dice(emoji="🎰")
        await asyncio.sleep(3)
        value = msg.dice.value
        if value == 64:
            text = "Джекпот!"
        elif value > 40:
            text = "Неплохо."
        else:
            text = "Пусто."
        await message.answer(text)
    except Exception as e:
        logger.error(f"/burmalda error: {e}")

@dp.message(Command("malfoy"))
async def cmd_malfoy(message: Message) -> None:
    thinking_msg = await message.answer(
        "🐍 *Люциус Малфой поправляет мантию и задумчиво смотрит на тебя...*",
        parse_mode="Markdown"
    )
    malfoy_response = await get_malfoy_response()
    await thinking_msg.delete()
    await message.answer(f"🐍 {malfoy_response}")

@dp.message(is_user_filter, F.text.startswith("/"))
async def handle_unknown_command(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n\n"
        "/start — 👋 Старт\n"
        "/chat — 🤫 Чат с поддержкой\n"
        "/luck — 🎲 Кинуть кость\n"
        "/burmalda — 🎰 Бурмалда\n"
        "/malfoy — 🐍 Малфой",
        reply_markup=user_keyboard()  # Показываем клавиатуру при ошибке
    )

@dp.message(is_user_filter)
async def handle_user_message(message: Message) -> None:
    # Игнорируем кнопки
    if message.text in [BTN_START, BTN_CHAT, BTN_LUCK, BTN_BURMALDA, BTN_MALFOY, BTN_STOP]:
        return
        
    if message.chat.id not in active_chat_users:
        # Если пользователь не в чате, показываем клавиатуру
        await message.answer(
            "Используй кнопки ниже для навигации.",
            reply_markup=user_keyboard()
        )
        return
    
    track_user(message)
    await forward_to_admin(message)

# ──────────────────────────────────────────────
# Веб-сервер для Render
# ──────────────────────────────────────────────

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        return

def run_web_server():
    try:
        server_address = ("0.0.0.0", PORT)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"Web server on port {PORT}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Web server error: {e}")

async def setup_commands() -> None:
    user_commands = [
        BotCommand(command="start", description="👋 Старт"),
        BotCommand(command="chat", description="🤫 Чат с поддержкой"),
        BotCommand(command="luck", description="🎲 Кинуть кость"),
        BotCommand(command="burmalda", description="🎰 Бурмалда"),
        BotCommand(command="malfoy", description="🐍 Малфой"),
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
    logger.info("Starting Malfoy Bot...")
    
    # Веб-сервер
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Сбрасываем старые обновления
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Команды
    await setup_commands()
    
    logger.info("Bot is running!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
