import asyncio
import logging
import os
import random
import uvicorn
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable

import db
from app import app as fastapi_app

# Для Railway и других платформ, которые ищут переменную 'app'
app = fastapi_app

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [1562788488, 8565678796] # Замените на реальные ID админов
CHANNEL_URL = "https://t.me/officialWizzi" # Вставьте вашу ссылку на ПЕРВЫЙ канал
CHANNEL_ID = "@officialWizzi" # Вставьте ID ПЕРВОГО канала
CHANNEL_URL_2 = "https://t.me/Tournament_Evo" # Вставьте вашу ссылку на ВТОРОЙ канал
CHANNEL_ID_2 = "@Tournament_Evo" # Вставьте ID ВТОРОГО канала

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def main():
    db.init_db()
    
    # Восстановление состояния лобби из БД при запуске
    lobby_members = db.get_all_lobby_members()
    for uid, mode, lid in lobby_members:
        user = db.get_user(uid)
        if user:
            lvl = db.get_level_by_elo(user[2])
            state.lobby_players[mode][lid][uid] = {
                "nickname": user[1], 
                "level": lvl, 
                "game_id": user[0]
            }
    
    # Запуск бота и FastAPI сервера параллельно
    # Render передает PORT через переменную окружения
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, types.Message):
            user_id = event.from_user.id
            # Пропускаем команду /start и проверку подписки, чтобы не было цикла
            if event.text == "/start":
                return await handler(event, data)
        elif isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            if event.data == "check_sub":
                return await handler(event, data)
        
        if user_id:
            # Игнорируем проверку для админов (опционально, но удобно для тестов)
            if user_id in ADMINS:
                return await handler(event, data)

            if not await check_subscription(user_id):
                builder = InlineKeyboardBuilder()
                builder.row(types.InlineKeyboardButton(text="Подписаться на 1-й канал 📢", url=CHANNEL_URL))
                builder.row(types.InlineKeyboardButton(text="Подписаться на 2-й канал 📢", url=CHANNEL_URL_2))
                builder.row(types.InlineKeyboardButton(text="Я подписался на оба ✅", callback_data="check_sub"))
                
                msg_text = "👋 Для использования бота необходимо быть подписанным на оба наших канала."
                if isinstance(event, types.Message):
                    await event.answer(msg_text, reply_markup=builder.as_markup())
                elif isinstance(event, types.CallbackQuery):
                    try:
                        await event.message.answer(msg_text, reply_markup=builder.as_markup())
                        await event.answer()
                    except TelegramBadRequest:
                        pass
                return

        return await handler(event, data)

class MenuMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]],
        event: types.Message,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, types.Message):
            # Если это текстовая команда меню
            if event.text in ["Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"]:
                state = data.get("state")
                if state:
                    await state.clear()
                
                # Принудительно обновляем клавиатуру при каждом нажатии кнопки меню
                # Это гарантирует, что кнопки (Настройки/Админ) не пропадут
                try:
                    user_id = event.from_user.id
                    # Чтобы не дублировать сообщения, мы просто добавляем reply_markup к текущему ответу
                    # Но middleware срабатывает ДО хендлера. 
                    # Поэтому мы просто полагаемся на то, что все хендлеры меню теперь используют main_menu_keyboard(user_id)
                except: pass
                
        return await handler(event, data)

dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())
dp.message.middleware(MenuMiddleware())

import state

# Глобальные состояния теперь в state.py
lobby_players = state.lobby_players
lobby_viewers = state.lobby_viewers
active_matches = state.active_matches
pending_matches = state.pending_matches
admin_messages = state.admin_messages
support_requests = state.support_requests

MAP_LIST_2X2 = ["Sandstone", "Province", "Breeze", "Dune", "Zone 7", "Rust", "Hanami"]
MAP_LIST_1X1 = ["Temple", "Yard", "Bridge", "Pool", "Desert", "Pipeline", "Cableway"]

# Состояния регистрации
class Registration(StatesGroup):
    waiting_for_game_id = State()
    waiting_for_nickname = State()

class MatchResult(StatesGroup):
    waiting_for_screenshot = State()

class SupportState(StatesGroup):
    waiting_for_message = State()
    waiting_for_admin_reply = State()

class SettingsState(StatesGroup):
    waiting_for_new_nickname = State()
    waiting_for_new_game_id = State()

class AdminAction(StatesGroup):
    waiting_for_ban_reason = State()
    waiting_for_message_text = State()
    waiting_for_elo_change = State()
    waiting_for_stats_change = State()

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Регистрация в общей БД, если пользователя еще нет
    if not db.get_user(user_id):
        db.register_user(user_id, username)
        logging.info(f"Новый пользователь зарегистрирован: {username} ({user_id})")

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Добро пожаловать в **Yoda Faceit** — лучшую арену для Project Evolution.\n\n"
        "Жми кнопку ниже, чтобы войти в игру!",
        reply_markup=main_menu_keyboard(user_id)
    )

def main_menu_keyboard(user_id=None):
    # Единственная кнопка для бесшовного перехода в Mini App
    builder = ReplyKeyboardBuilder()
    # В идеале здесь должна быть ваша ссылка на Railway
    mini_app_url = os.getenv("MINI_APP_URL", "https://ВАШ-ПРОЕКТ.up.railway.app/")
    
    builder.row(types.KeyboardButton(
        text="Играть в Yoda Faceit 🎮", 
        web_app=types.WebAppInfo(url=mini_app_url)
    ))
    return builder.as_markup(resize_keyboard=True, persistent=True)

def get_lobby_keyboard(user_id, mode, lobby_id):
    builder = InlineKeyboardBuilder()
    players_in_lobby = lobby_players[mode][lobby_id]
    
    if mode == "1x1":
        max_players = 2
    elif mode == "2x2":
        max_players = 4
    else: # 5x5
        max_players = 10
    
    if user_id not in players_in_lobby:
        builder.row(types.InlineKeyboardButton(
            text=f"Войти в лобби {lobby_id} 🎮 ({len(players_in_lobby)}/{max_players})", 
            callback_data=f"l_enter_{mode}_{lobby_id}"
        ))
    else:
        builder.row(types.InlineKeyboardButton(
            text="Выйти из лобби ❌", 
            callback_data=f"l_exit_{mode}_{lobby_id}"
        ))
    
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад к выбору лобби", callback_data=f"mode_{mode}"))
    return builder.as_markup()

def get_mode_selection_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⚔️ 1 на 1", callback_data="mode_1x1"),
        types.InlineKeyboardButton(text="🔫 2 на 2", callback_data="mode_2x2")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔥 5 на 5", callback_data="mode_5x5")
    )
    return builder.as_markup()

def get_lobby_list_keyboard(mode):
    builder = InlineKeyboardBuilder()
    if mode == "1x1":
        max_p = 2
    elif mode == "2x2":
        max_p = 4
    else: # 5x5
        max_p = 10
        
    for lid in range(1, 11):
        count = len(lobby_players[mode][lid])
        builder.row(types.InlineKeyboardButton(
            text=f"Лобби №{lid} [{count}/{max_p}]", 
            callback_data=f"view_l_{mode}_{lid}"
        ))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад к режимам", callback_data="back_to_modes"))
    return builder.as_markup()

async def update_all_lobby_messages(mode, lobby_id):
    players_in_lobby = lobby_players[mode][lobby_id]
    if mode == "1x1":
        max_p = 2
    elif mode == "2x2":
        max_p = 4
    else: # 5x5
        max_p = 10
        
    status_text = f"📍 Режим: {mode} | Лобби №{lobby_id} ({len(players_in_lobby)}/{max_p})\n\nСписок игроков 🎮:\n"
    
    if not players_in_lobby:
        status_text += "Пусто..."
    else:
        for uid, data in players_in_lobby.items():
            status_text += f"👤 {data['nickname']} | Lvl: {data['level']}\n"
    
    # Обновляем сообщения у всех, кто смотрит ИМЕННО ЭТО лобби
    dead_viewers = []
    for uid, data in lobby_viewers.items():
        if data.get("mode") == mode and data.get("lobby_id") == lobby_id:
            try:
                await bot.edit_message_text(
                    text=status_text,
                    chat_id=data['chat_id'],
                    message_id=data['message_id'],
                    reply_markup=get_lobby_keyboard(uid, mode, lobby_id)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e): continue
                dead_viewers.append(uid)
            except Exception:
                dead_viewers.append(uid)
            
    for uid in dead_viewers:
        if uid in lobby_viewers: del lobby_viewers[uid]

async def update_lobby_list_for_all(mode):
    # Обновляем список лобби для тех, кто находится на экране выбора лобби этого режима
    for uid, data in lobby_viewers.items():
        if data.get("mode") == mode and data.get("lobby_id") is None:
            try:
                await bot.edit_message_text(
                    text=f"Выбран режим: {mode}. Выберите свободное лобби:",
                    chat_id=data['chat_id'],
                    message_id=data['message_id'],
                    reply_markup=get_lobby_list_keyboard(mode)
                )
            except: pass

async def check_subscription(user_id: int) -> bool:
    try:
        # Проверка первого канала
        member1 = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        is_sub1 = member1.status in ["member", "administrator", "creator"]
        
        # Проверка второго канала
        member2 = await bot.get_chat_member(chat_id=CHANNEL_ID_2, user_id=user_id)
        is_sub2 = member2.status in ["member", "administrator", "creator"]
        
        return is_sub1 and is_sub2
    except Exception:
        # Если бот не админ в каком-то канале или канал не найден, 
        # для безопасности считаем что подписан, чтобы не блокировать всех
        return True

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                # Время бана истекло
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы навсегда.")
            return

    # Проверка подписки
    if not await check_subscription(message.from_user.id):
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="Подписаться на 1-й канал 📢", url=CHANNEL_URL))
        builder.row(types.InlineKeyboardButton(text="Подписаться на 2-й канал 📢", url=CHANNEL_URL_2))
        builder.row(types.InlineKeyboardButton(text="Я подписался на оба ✅", callback_data="check_sub"))
        await message.answer(
            "👋 Привет! Для использования бота необходимо быть подписанным на оба наших канала.",
            reply_markup=builder.as_markup()
        )
        return

    await state.clear()
    user = db.get_user(message.from_user.id)
    if user:
        await message.answer(
            f"С возвращением, {user[1]}! 👋\nТы в главном меню.",
            reply_markup=main_menu_keyboard(message.from_user.id)
        )
    else:
        await message.answer(
            "Привет! 👋 Это Faceit для Project Evolution.\n"
            "⚠️ ВНИМАНИЕ: Ваш никнейм в боте ДОЛЖЕН совпадать с никнеймом в игре!\n\n"
            "Для начала работы нужно зарегистрироваться.\n"
            "Введите ваш игровой ID (8-9 цифр):"
        )
        await state.set_state(Registration.waiting_for_game_id)

@dp.callback_query(F.data == "check_sub")
async def handle_check_sub(callback: types.CallbackQuery, state: FSMContext):
    if await check_subscription(callback.from_user.id):
        try: await callback.answer("Подписка подтверждена! ✅")
        except TelegramBadRequest: pass
        await cmd_start(callback.message, state)
    else:
        try: await callback.answer("Вы всё ещё не подписаны! ❌", show_alert=True)
        except TelegramBadRequest: pass

@dp.message(Registration.waiting_for_game_id)
async def process_game_id(message: types.Message, state: FSMContext):
    # Фильтрация кнопок меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    if not message.text or not message.text.isdigit() or not (8 <= len(message.text) <= 9):
        await message.answer("Ошибка! ID должен состоять только из цифр (8-9 знаков):")
        return
    await state.update_data(game_id=message.text)
    await message.answer("⚠️ Напоминание: Никнейм должен быть как в игре!\nВведите ваш никнейм:")
    await state.set_state(Registration.waiting_for_nickname)

@dp.message(Registration.waiting_for_nickname)
async def process_nickname(message: types.Message, state: FSMContext):
    # Фильтрация кнопок меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    nickname = message.text.strip() if message.text else ""
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("Никнейм от 2 до 20 символов:")
        return
    user_data = await state.get_data()
    db.add_user(message.from_user.id, user_data['game_id'], nickname)
    await state.clear()
    await message.answer(f"Регистрация завершена! 🎉\nНик: {nickname}\nID: {user_data['game_id']}\nLvl: 4", reply_markup=main_menu_keyboard(message.from_user.id))

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы.")
            return

    # Проверка подписки
    if not await check_subscription(message.from_user.id):
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="Подписаться на 1-й канал 📢", url=CHANNEL_URL))
        builder.row(types.InlineKeyboardButton(text="Подписаться на 2-й канал 📢", url=CHANNEL_URL_2))
        builder.row(types.InlineKeyboardButton(text="Я подписался на оба ✅", callback_data="check_sub"))
        await message.answer(
            "👋 Для доступа к функциям бота необходимо быть подписанным на оба наших канала.",
            reply_markup=builder.as_markup()
        )
        return

    user = db.get_user(message.from_user.id)
    if not user: return
    game_id, nickname, elo, level, matches, wins = user
    # Вычисляем уровень на лету на основе ELO
    level = db.get_level_by_elo(elo)
    winrate = (wins / matches * 100) if matches > 0 else 0
    await message.answer(
        f"👤 Профиль: {nickname}\n🆔 ID: {game_id}\n⭐ Lvl: {level}\n🏆 ELO: {elo}\n🎮 Матчей: {matches}\n📈 Винрейт: {winrate:.1f}%",
        reply_markup=main_menu_keyboard(message.from_user.id)
    )

@dp.message(F.text == "Поиск матча 🔍")
async def find_match(message: types.Message):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы.")
            return

    # Проверка подписки
    if not await check_subscription(message.from_user.id):
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="Подписаться на 1-й канал 📢", url=CHANNEL_URL))
        builder.row(types.InlineKeyboardButton(text="Подписаться на 2-й канал 📢", url=CHANNEL_URL_2))
        builder.row(types.InlineKeyboardButton(text="Я подписался на оба ✅", callback_data="check_sub"))
        await message.answer(
            "👋 Для доступа к поиску матча необходимо быть подписанным на оба наших канала.",
            reply_markup=builder.as_markup()
        )
        return

    user = db.get_user(message.from_user.id)
    if not user: return
    
    # Сначала выбор режима
    msg = await message.answer(
        "🎮 ВЫБОР РЕЖИМА ИГРЫ\n\n"
        "Выберите режим, в котором хотите соревноваться:",
        reply_markup=get_mode_selection_keyboard()
    )
    lobby_viewers[message.from_user.id] = {"mode": None, "lobby_id": None, "message_id": msg.message_id, "chat_id": msg.chat.id}

@dp.callback_query(F.data == "back_to_modes")
async def back_to_modes(callback: types.CallbackQuery):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == callback.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        try: await callback.answer("❌ Вы заблокированы.", show_alert=True)
        except TelegramBadRequest: pass
        return

    try: await callback.answer()
    except TelegramBadRequest: pass

    await callback.message.edit_text(
        "🎮 ВЫБОР РЕЖИМА ИГРЫ\n\n"
        "Выберите режим, в котором хотите соревноваться:",
        reply_markup=get_mode_selection_keyboard()
    )
    # Обновляем инфо о зрителе
    lobby_viewers[callback.from_user.id] = {
        "mode": None, 
        "lobby_id": None,
        "message_id": callback.message.message_id,
        "chat_id": callback.message.chat.id
    }
    await callback.answer()

@dp.callback_query(F.data.startswith("mode_"))
async def select_mode(callback: types.CallbackQuery):
    await callback.answer()
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == callback.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        await callback.answer("❌ Вы заблокированы.", show_alert=True)
        return

    mode = callback.data.split("_")[1]
    await callback.message.edit_text(
        f"Выбран режим: {mode}. Выберите свободное лобби:",
        reply_markup=get_lobby_list_keyboard(mode)
    )
    # Обновляем инфо о зрителе
    lobby_viewers[callback.from_user.id] = {
        "mode": mode, 
        "lobby_id": None,
        "message_id": callback.message.message_id,
        "chat_id": callback.message.chat.id
    }

@dp.callback_query(F.data.startswith("view_l_"))
async def view_lobby(callback: types.CallbackQuery):
    await callback.answer()
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == callback.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        await callback.answer("❌ Вы заблокированы.", show_alert=True)
        return

    try:
        _, _, mode, lobby_id = callback.data.split("_")
        lobby_id = int(lobby_id)
        
        # Обновляем инфо о зрителе
        lobby_viewers[callback.from_user.id] = {
            "mode": mode, 
            "lobby_id": lobby_id, 
            "message_id": callback.message.message_id,
            "chat_id": callback.message.chat.id
        }
        
        players_in_lobby = lobby_players[mode][lobby_id]
        if mode == "1x1":
            max_players = 2
        elif mode == "2x2":
            max_players = 4
        else: # 5x5
            max_players = 10
        
        text = f"🎮 ЛОББИ {lobby_id} ({mode})\nИгроков: {len(players_in_lobby)}/{max_players}\n\n"
        
        if players_in_lobby:
            for uid, p_data in players_in_lobby.items():
                text += f"• {p_data['nickname']} (Lvl {p_data['level']})\n"
        else:
            text += "Лобби пусто.\n"
            
        await callback.message.edit_text(text, reply_markup=get_lobby_keyboard(callback.from_user.id, mode, lobby_id))
    except Exception as e:
        logging.error(f"Error in view_lobby: {e}")
    finally:
        await callback.answer()

@dp.callback_query(F.data.startswith("l_enter_"))
async def lobby_enter_callback(callback: types.CallbackQuery):
    # Принудительно подтверждаем callback сразу для отзывчивости
    await callback.answer()
    
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == callback.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        await callback.message.answer("❌ Вы заблокированы.")
        return

    _, _, mode, lobby_id = callback.data.split("_")
    lobby_id = int(lobby_id)
    user_id = callback.from_user.id
    
    # Обновляем инфо о зрителе (гарантируем актуальность message_id)
    lobby_viewers[user_id] = {
        "mode": mode, 
        "lobby_id": lobby_id, 
        "message_id": callback.message.message_id,
        "chat_id": callback.message.chat.id
    }
    
    # Проверка, не в другом ли лобби игрок
    for m in lobby_players:
        for lid in lobby_players[m]:
            if user_id in lobby_players[m][lid]:
                # Если он в ЭТОМ ЖЕ лобби, просто обновляем сообщение (могло рассинхрониться)
                if m == mode and lid == lobby_id:
                    await update_all_lobby_messages(mode, lobby_id)
                    await callback.answer("Вы уже в этом лобби.")
                else:
                    # Если он числится в другом лобби, но пытается войти в это
                    # Возможно, это рассинхрон после перезапуска. 
                    # Удаляем из памяти и из БД
                    del lobby_players[m][lid][user_id]
                    db.remove_lobby_member(user_id)
                    await update_all_lobby_messages(m, lid)
                    # И продолжаем вход в новое...
                    break 
        else:
            continue
        break

    user = db.get_user(user_id)
    if not user:
        await callback.answer("Ошибка: пользователь не найден в БД.", show_alert=True)
        return
        
    level = db.get_level_by_elo(user[2])
    
    # Атомарная проверка вместимости перед входом
    if mode == "1x1":
        max_p = 2
    elif mode == "2x2":
        max_p = 4
    else: # 5x5
        max_p = 10
        
    if len(lobby_players[mode][lobby_id]) >= max_p:
        await callback.answer("Лобби уже заполнено!", show_alert=True)
        return

    lobby_players[mode][lobby_id][user_id] = {"nickname": user[1], "level": level, "game_id": user[0]}
    db.add_lobby_member(mode, lobby_id, user_id)
    # Используем message.answer вместо callback.answer для надежности отображения
    await callback.message.answer(f"✅ Вы вошли в лобби №{lobby_id} ({mode})")
    
    await update_all_lobby_messages(mode, lobby_id)
    await update_lobby_list_for_all(mode)
    
    if len(lobby_players[mode][lobby_id]) >= max_p:
        # Небольшая задержка перед подтверждением, чтобы пользователи увидели заполнение
        await asyncio.sleep(0.5)
        await request_match_accept(mode, lobby_id)

async def request_match_accept(mode, lobby_id):
    if not lobby_players[mode][lobby_id]:
        return
        
    players = list(lobby_players[mode][lobby_id].items())
    player_ids = [uid for uid, _ in players]
    
    # Удаляем участников лобби из БД при создании матча
    for uid in player_ids:
        db.remove_lobby_member(uid)
        
    lobby_players[mode][lobby_id].clear()
    
    match_num = db.create_match(mode, player_ids)
    
    pending_matches[match_num] = {
        "players": players,
        "accepted": set(),
        "messages": {},
        "mode": mode
    }
    
    # Убираем всех из зрителей (чтобы не спамило обновлениями)
    for uid, _ in players:
        if uid in lobby_viewers: del lobby_viewers[uid]
    
    await update_lobby_list_for_all(mode) # Обновляем список лобби (теперь оно пустое)
        
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Принять ✅", callback_data=f"accept_{match_num}"))
    
    for uid, _ in players:
        try:
            msg = await bot.send_message(uid, f"🔔 Игра {mode} найдена! Подтвердите участие (Матч №{match_num})\nУ вас есть 60 секунд.", reply_markup=builder.as_markup())
            pending_matches[match_num]["messages"][uid] = msg.message_id
        except: pass
    
    asyncio.create_task(check_accept_timeout(match_num))

async def check_accept_timeout(match_num):
    await asyncio.sleep(60) 
    if match_num in pending_matches:
        match = pending_matches[match_num]
        accepted_ids = match["accepted"]
        mode = match["mode"]
        
        # Кто не принял
        not_accepted = [p for p in match["players"] if p[0] not in accepted_ids]
        # Кто принял
        accepted_players = [p for p in match["players"] if p[0] in accepted_ids]
        
        # Обработка тех, кто не принял
        for p_uid, p_data in not_accepted:
            # Инкремент предупреждений
            count = db.increment_missed_games(p_uid)
            
            try:
                if count >= 3:
                    # Бан на 30 минут
                    ban_until = datetime.now() + timedelta(minutes=30)
                    until_str = ban_until.strftime("%Y-%m-%d %H:%M:%S")
                    db.set_ban_status(p_uid, True, until_str)
                    db.reset_missed_games(p_uid)
                    await bot.send_message(p_uid, f"❌ Вы не подтвердили игру (3/3). Бан на 30 минут до {until_str}.")
                else:
                    await bot.send_message(p_uid, f"⚠️ Вы не подтвердили игру! Предупреждение: {count}/3. При 3/3 — бан на 30 минут.")
                
                # Убираем кнопки у опоздавшего
                await bot.edit_message_text("Вы не подтвердили игру и были кикнуты из очереди.", chat_id=p_uid, message_id=match["messages"].get(p_uid))
            except: pass

        # Обработка тех, кто принял
        if accepted_players:
            # Возвращаем их в лобби (или просто уведомляем, что они остаются в очереди)
            # Находим свободное лобби для них или создаем видимость, что они там
            # Но по логике текущего кода, лобби было очищено. 
            # Нам нужно найти ПЕРВОЕ свободное лобби этого режима и закинуть их туда.
            
            target_lobby_id = 1
            for lid in range(1, 11):
                if len(lobby_players[mode][lid]) == 0:
                    target_lobby_id = lid
                    break
            
            for p_uid, p_data in accepted_players:
                try:
                    # Возвращаем в память
                    lobby_players[mode][target_lobby_id][p_uid] = p_data
                    # Возвращаем в БД
                    db.add_lobby_member(mode, target_lobby_id, p_uid)
                    
                    await bot.edit_message_text(f"Матч отменен: не все игроки подтвердили участие.\nВы возвращены в лобби №{target_lobby_id}.", chat_id=p_uid, message_id=match["messages"].get(p_uid))
                except: pass
            
            await update_all_lobby_messages(mode, target_lobby_id)
            await update_lobby_list_for_all(mode)

        db.cancel_match(match_num)
        if match_num in pending_matches:
            del pending_matches[match_num]

@dp.callback_query(F.data.startswith("accept_"))
async def handle_accept(callback: types.CallbackQuery):
    await callback.answer()
    match_num = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Сначала пытаемся найти в памяти
    if match_num not in pending_matches:
        # Если в памяти нет (после перезагрузки), проверяем БД
        match_db = db.get_pending_match(match_num)
        if not match_db:
            await callback.answer("Матч уже отменен, не существует или уже начат.", show_alert=True)
            return
            
        # Восстанавливаем в памяти из БД
        players_db = db.get_match_players(match_num)
        # [(user_id, nickname, elo, level, accepted), ...]
        
        # Нам нужно восстановить players как список кортежей (uid, data_dict)
        restored_players = []
        accepted_set = set()
        for p in players_db:
            uid, nick, elo, lvl, accepted = p
            u_full = db.get_user(uid)
            gid = u_full[0] if u_full else str(uid)
            
            p_data = {"nickname": nick, "level": lvl, "game_id": gid}
            restored_players.append((uid, p_data))
            if accepted:
                accepted_set.add(uid)
        
        pending_matches[match_num] = {
            "players": restored_players,
            "accepted": accepted_set,
            "messages": {}, # Сообщения восстановить нельзя, но кнопки нажать можно
            "mode": match_db[1]
        }
        
    match = pending_matches[match_num]
    
    if user_id in match["accepted"]:
        # await callback.answer("Вы уже подтвердили участие.") # Уже подтвердили callback в начале
        return
        
    match["accepted"].add(user_id)
    db.accept_match_player(match_num, user_id)
    
    try:
        await callback.message.edit_text("Вы подтвердили участие! Ожидание остальных... ⏳")
    except:
        await callback.answer("Вы подтвердили участие!")
    
    if len(match["accepted"]) == len(match["players"]):
        players = match["players"]
        mode = match["mode"]
        if match_num in pending_matches:
            del pending_matches[match_num]
        await start_match_setup(match_num, players, mode)

async def start_match_setup(match_num, players, mode):
    random.shuffle(players)
    
    if mode == "1x1":
        # В режиме 1 на 1 нет выбора капитанов и пика игроков
        p1 = players[0]
        p2 = players[1]
        
        active_matches[match_num] = {
            "players": players,
            "mode": "1x1",
            "maps": MAP_LIST_1X1.copy(),
            "turn": "p1",
            "phase": "ban",
            "teams": {"ct": [p1], "t": [p2]},
            "final_map": None,
            "elo_gain": random.randint(5, 15),
            "message_ids": {}
        }
        for uid, _ in players:
            await bot.send_message(uid, f"🔔 ВСЕ ПОДТВЕРДИЛИ! (Матч 1x1 №{match_num})\n\nНачинаем бан карт.")
        await send_map_selection(match_num)
    elif mode == "2x2":
        # Режим 2x2 - стандартная логика с капитанами
        cap_ct = players[0]
        cap_t = players[1]
        available_players = [p for p in players if p[0] not in [cap_ct[0], cap_t[0]]]
        
        active_matches[match_num] = {
            "players": players,
            "mode": "2x2",
            "available_players": available_players, 
            "captains": {"ct": cap_ct[0], "t": cap_t[0]},
            "maps": MAP_LIST_2X2.copy(),
            "turn": "ct",
            "phase": "ban",
            "teams": {"ct": [cap_ct], "t": [cap_t]},
            "final_map": None,
            "elo_gain": random.randint(20, 30),
            "message_ids": {}
        }
        for uid, _ in players:
            await bot.send_message(uid, f"🔔 ВСЕ ПОДТВЕРДИЛИ! (Матч 2x2 №{match_num})\nКапитан CT: {cap_ct[1]['nickname']}\nКапитан T: {cap_t[1]['nickname']}\n\nНачинаем бан карт. Первые банят CT.")
        await send_map_selection(match_num)
    else: # 5x5
        # Режим 5x5 - логика как в 2x2, но мап-пул такой же (по условию)
        cap_ct = players[0]
        cap_t = players[1]
        available_players = [p for p in players if p[0] not in [cap_ct[0], cap_t[0]]]
        
        active_matches[match_num] = {
            "players": players,
            "mode": "5x5",
            "available_players": available_players, 
            "captains": {"ct": cap_ct[0], "t": cap_t[0]},
            "maps": MAP_LIST_2X2.copy(), # Тот же мап-пул
            "turn": "ct",
            "phase": "ban",
            "teams": {"ct": [cap_ct], "t": [cap_t]},
            "final_map": None,
            "elo_gain": random.randint(25, 35),
            "message_ids": {}
        }
        for uid, _ in players:
            await bot.send_message(uid, f"🔔 ВСЕ ПОДТВЕРДИЛИ! (Матч 5x5 №{match_num})\nКапитан CT: {cap_ct[1]['nickname']}\nКапитан T: {cap_t[1]['nickname']}\n\nНачинаем бан карт. Первые банят CT.")
        await send_map_selection(match_num)

async def auto_ban_timer(match_id, turn_at_start):
    await asyncio.sleep(30)
    if match_id not in active_matches: return
    match = active_matches[match_id]
    if match.get("phase") != "ban" or match.get("turn") != turn_at_start: return
    
    # Если время вышло и это всё еще тот же ход и фаза бана
    map_to_ban = random.choice(match["maps"])
    match["maps"].remove(map_to_ban)
    
    if len(match["maps"]) > 1:
        if match.get("mode") == "1x1":
            match["turn"] = "p2" if match["turn"] == "p1" else "p1"
        else:
            match["turn"] = "t" if match["turn"] == "ct" else "ct"
        await send_map_selection(match_id)
    else:
        match["final_map"] = match["maps"][0]
        for uid, msg_id in match.get("message_ids", {}).items():
            try: await bot.delete_message(chat_id=uid, message_id=msg_id)
            except: pass
        match["message_ids"] = {}
        
        if match.get("mode") in ["2x2", "5x5"]:
            match["phase"] = "pick"
            match["turn"] = "t"
            for uid, _ in match["players"]:
                await bot.send_message(uid, f"Время вышло! Карта определена автоматически: {match['final_map']}!\nПереходим к выбору игроков.")
            await send_player_selection(match_id)
        else:
            await finish_match_setup(match_id)

async def auto_pick_timer(match_id, turn_at_start):
    await asyncio.sleep(30)
    if match_id not in active_matches: return
    match = active_matches[match_id]
    if match.get("phase") != "pick" or match.get("turn") != turn_at_start: return
    
    # Если время вышло и это всё еще тот же ход и фаза пика
    picked_player = random.choice(match["available_players"])
    match["teams"][match["turn"]].append(picked_player)
    match["available_players"].remove(picked_player)
    
    if match["available_players"]:
        match["turn"] = "ct" if match["turn"] == "t" else "t"
        await send_player_selection(match_id)
    else:
        for uid, msg_id in match.get("message_ids", {}).items():
            try: await bot.delete_message(chat_id=uid, message_id=msg_id)
            except: pass
        match["message_ids"] = {}
        await finish_match_setup(match_id)

async def send_map_selection(match_id):
    match = active_matches[match_id]
    builder = InlineKeyboardBuilder()
    
    # Кнопки в 2 столбика
    buttons = []
    for m in match['maps']:
        buttons.append(types.InlineKeyboardButton(text=f"Бан {m}", callback_data=f"ban_{match_id}_{m}"))
    
    # Группируем по 2
    for i in range(0, len(buttons), 2):
        builder.row(*buttons[i:i+2])
    
    if match.get("mode") == "1x1":
        p1_name = match['players'][0][1]['nickname']
        p2_name = match['players'][1][1]['nickname']
        turn_text = f"игрока {p1_name if match['turn'] == 'p1' else p2_name}"
        current_turn_uid = match['players'][0 if match['turn'] == 'p1' else 1][0]
    else:
        turn_text = f"капитана {'CT' if match['turn'] == 'ct' else 'T'}"
        current_turn_uid = match['captains'][match['turn']]
        
    text = f"⏳ У вас 30 секунд!\nЭтап: БАН КАРТ\nХод {turn_text}\nКарты в пуле: {', '.join(match['maps'])}"
    
    # Запускаем таймер авто-бана
    asyncio.create_task(auto_ban_timer(match_id, match['turn']))
    
    for uid, _ in match['players']:
        markup = builder.as_markup() if uid == current_turn_uid else None
        msg_text = text if uid == current_turn_uid else f"{text}\n(Ожидание хода противника)"
        
        if uid in match.get("message_ids", {}):
            try:
                await bot.edit_message_text(
                    chat_id=uid,
                    message_id=match["message_ids"][uid],
                    text=msg_text,
                    reply_markup=markup
                )
            except:
                # Если сообщение нельзя редактировать, отправляем новое
                new_msg = await bot.send_message(uid, msg_text, reply_markup=markup)
                match["message_ids"][uid] = new_msg.message_id
        else:
            new_msg = await bot.send_message(uid, msg_text, reply_markup=markup)
            if "message_ids" not in match: match["message_ids"] = {}
            match["message_ids"][uid] = new_msg.message_id

@dp.callback_query(F.data.startswith("ban_"))
async def handle_ban(callback: types.CallbackQuery):
    _, match_id, map_name = callback.data.split("_")
    match_id = int(match_id)
    match = active_matches[match_id]
    
    if match.get("mode") == "1x1":
        current_turn_uid = match['players'][0 if match['turn'] == 'p1' else 1][0]
    else:
        current_turn_uid = match['captains'][match['turn']]
        
    if callback.from_user.id != current_turn_uid: 
        await callback.answer("Сейчас не ваш ход!", show_alert=True)
        return
    
    await callback.answer(f"Вы забанили {map_name}")
    match['maps'].remove(map_name)
    
    if len(match['maps']) > 1:
        if match.get("mode") == "1x1":
            match['turn'] = "p2" if match['turn'] == "p1" else "p1"
        else:
            match['turn'] = "t" if match['turn'] == "ct" else "ct"
        await send_map_selection(match_id)
    else:
        match['final_map'] = match['maps'][0]
        # Очищаем старые сообщения перед переходом к следующей фазе
        for uid, msg_id in match.get("message_ids", {}).items():
            try: await bot.delete_message(chat_id=uid, message_id=msg_id)
            except: pass
        match["message_ids"] = {}
        
        if match.get("mode") in ["2x2", "5x5"]:
            match['phase'] = "pick"
            match['turn'] = "t"
            for uid, _ in match['players']:
                await bot.send_message(uid, f"Карта определена: {match['final_map']}!\nПереходим к выбору игроков. Первые выбирают T.")
            await send_player_selection(match_id)
        else:
            # В 1x1 сразу финиш
            await finish_match_setup(match_id)

async def send_player_selection(match_id):
    match = active_matches[match_id]
    builder = InlineKeyboardBuilder()
    for p_id, p_data in match['available_players']:
        builder.row(types.InlineKeyboardButton(text=f"Пик {p_data['nickname']} (Lvl {p_data['level']})", callback_data=f"pick_{match_id}_{p_id}"))
    
    avail_nicks = [p[1]['nickname'] for p in match['available_players']]
    text = f"⏳ У вас 30 секунд!\nЭтап: ПИК ИГРОКОВ\nХод капитана {'CT' if match['turn'] == 'ct' else 'T'}\nДоступны: {', '.join(avail_nicks)}"
    current_cap = match['captains'][match['turn']]
    
    # Запускаем таймер авто-пика
    asyncio.create_task(auto_pick_timer(match_id, match['turn']))
    
    for uid, _ in match['players']:
        markup = builder.as_markup() if uid == current_cap else None
        msg_text = text if uid == current_cap else f"{text}\n(Ожидание хода капитана)"
        
        if uid in match.get("message_ids", {}):
            try:
                await bot.edit_message_text(
                    chat_id=uid,
                    message_id=match["message_ids"][uid],
                    text=msg_text,
                    reply_markup=markup
                )
            except:
                new_msg = await bot.send_message(uid, msg_text, reply_markup=markup)
                match["message_ids"][uid] = new_msg.message_id
        else:
            new_msg = await bot.send_message(uid, msg_text, reply_markup=markup)
            match["message_ids"][uid] = new_msg.message_id

@dp.callback_query(F.data.startswith("pick_"))
async def handle_pick(callback: types.CallbackQuery):
    _, match_id, p_id = callback.data.split("_")
    match_id, p_id = int(match_id), int(p_id)
    match = active_matches[match_id]
    if callback.from_user.id != match['captains'][match['turn']]: 
        await callback.answer("Сейчас не ваш ход!", show_alert=True)
        return
    
    picked_player = next(p for p in match['available_players'] if p[0] == p_id)
    await callback.answer(f"Вы выбрали {picked_player[1]['nickname']}")
    
    match['teams'][match['turn']].append(picked_player)
    match['available_players'].remove(picked_player)
    
    if match['available_players']:
        match['turn'] = "ct" if match['turn'] == "t" else "t"
        await send_player_selection(match_id)
    else:
        # Очистка сообщений перед финалом
        for uid, msg_id in match.get("message_ids", {}).items():
            try: await bot.delete_message(chat_id=uid, message_id=msg_id)
            except: pass
        match["message_ids"] = {}
        await finish_match_setup(match_id)

async def finish_match_setup(match_id):
    match = active_matches[match_id]
    ct_team = "\n".join([f"• {p[1]['nickname']} (Lvl {p[1]['level']})" for p in match['teams']['ct']])
    t_team = "\n".join([f"• {p[1]['nickname']} (Lvl {p[1]['level']})" for p in match['teams']['t']])
    
    # В 1x1 капитаном считается первый игрок (CT)
    if match.get("mode") == "1x1":
        cap_ct_id = match['players'][0][1]['game_id']
    else:
        cap_ct_id = next(p[1]['game_id'] for p in match['players'] if p[0] == match['captains']['ct'])
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Отправить скриншот результата 📸", callback_data=f"result_{match_id}"))
    
    text = (
        f"🎮 МАТЧ ГОТОВ! (Матч №{match_id})\n"
        f"🗺 Карта: {match['final_map']}\n\n"
        f"🔵 КОМАНДА CT:\n{ct_team}\n"
        f"🔴 КОМАНДА T:\n{t_team}\n\n"
        f"👑 Капитан CT (ID в игре): {cap_ct_id}\n\n"
        f"📈 За победу: +{match['elo_gain']} ELO\n"
        f"📉 За поражение: -{match['elo_gain']} ELO\n\n"
        f"⚠️ Напоминание: Ваши никнеймы в игре ДОЛЖЕНЫ совпадать с никнеймами в боте!"
    )
    for uid, _ in match['players']:
        await bot.send_message(uid, text, reply_markup=builder.as_markup())
    
    # Отправка того же сообщения админам (если они не игроки в этом матче)
    player_ids = [p[0] for p in match['players']]
    for admin_id in ADMINS:
        if admin_id not in player_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=builder.as_markup())
            except: pass
    
    # Не удаляем матч сразу, чтобы кнопка скриншота работала
    # del active_matches[match_id]

@dp.callback_query(F.data.startswith("result_"))
async def handle_result_button(callback: types.CallbackQuery, state: FSMContext):
    match_id = int(callback.data.split("_")[1])
    await state.update_data(current_match_id=match_id)
    await state.set_state(MatchResult.waiting_for_screenshot)
    await callback.message.answer("Пожалуйста, отправьте скриншот результата этого матча:")
    await callback.answer()

@dp.message(MatchResult.waiting_for_screenshot)
async def process_screenshot(message: types.Message, state: FSMContext):
    # Фильтрация кнопок меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно ФОТО (скриншот) результата матча.")
        return

    data = await state.get_data()
    match_id = data.get("current_match_id")
    user = db.get_user(message.from_user.id)
    nickname = user[1] if user else "Unknown"
    
    # Кнопки для админов
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ CT WIN", callback_data=f"admin_win_{match_id}_ct"),
        types.InlineKeyboardButton(text="✅ T WIN", callback_data=f"admin_win_{match_id}_t")
    )
    builder.row(types.InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel_{match_id}"))
    
    # Пересылаем админам
    if match_id not in admin_messages:
        admin_messages[match_id] = {}
        
    for admin_id in ADMINS:
        try:
            # Сначала отправляем скриншот без кнопок с предупреждением
            msg = await bot.send_photo(
                admin_id, 
                message.photo[-1].file_id,
                caption=f"⚠️ ВНИМАНИЕ! Новый результат матча №{match_id}\nОтправил: {nickname} (ID: {message.from_user.id})\n\n⏳ Кнопки появятся через 3 секунды...",
            )
            
            # Фоновая задача для добавления кнопок через 3 секунды
            async def add_buttons_after_delay(admin_id, message_id, match_id, nickname, user_id):
                await asyncio.sleep(3)
                builder = InlineKeyboardBuilder()
                builder.row(
                    types.InlineKeyboardButton(text="✅ CT WIN", callback_data=f"admin_win_{match_id}_ct"),
                    types.InlineKeyboardButton(text="✅ T WIN", callback_data=f"admin_win_{match_id}_t")
                )
                builder.row(types.InlineKeyboardButton(text="🚫 Аннулировать одному", callback_data=f"admin_nullone_{match_id}"))
                builder.row(types.InlineKeyboardButton(text="❌ Отменить всем", callback_data=f"admin_cancel_{match_id}"))
                try:
                    await bot.edit_message_caption(
                        chat_id=admin_id,
                        message_id=message_id,
                        caption=f"🖼 Результат матча №{match_id}\nОтправил: {nickname} (ID: {user_id})\n\nВыберите победителя:",
                        reply_markup=builder.as_markup()
                    )
                except: pass

            asyncio.create_task(add_buttons_after_delay(admin_id, msg.message_id, match_id, nickname, message.from_user.id))
            
            if match_id not in admin_messages:
                admin_messages[match_id] = {}
            admin_messages[match_id][admin_id] = msg.message_id
        except Exception as e:
            logging.error(f"Failed to send to admin {admin_id}: {e}")
            
    await message.answer("Скриншот отправлен админам! Ожидайте подтверждения и обновления ELO. ✅")
    await state.clear()

@dp.callback_query(F.data.startswith("admin_nullone_"))
async def admin_nullify_one(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS: return
    match_id = int(callback.data.split("_")[2])
    
    if match_id not in active_matches:
        try: await callback.answer("Ошибка: матч не найден в активных!", show_alert=True)
        except TelegramBadRequest: pass
        return
        
    match = active_matches[match_id]
    builder = InlineKeyboardBuilder()
    
    # Создаем кнопки для каждого игрока в матче
    for team_name, players in match['teams'].items():
        for p_uid, p_data in players:
            nickname = p_data['nickname']
            builder.row(types.InlineKeyboardButton(
                text=f"👤 {nickname} ({team_name})", 
                callback_data=f"nullp_{match_id}_{p_uid}"
            ))
            
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_back_to_match_{match_id}"))
    
    await callback.message.edit_caption(
        caption=f"🚫 Выберите игрока для аннулирования результата в матче №{match_id}:",
        reply_markup=builder.as_markup()
    )
    try: await callback.answer()
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("nullp_"))
async def process_nullify_player(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS: return
    parts = callback.data.split("_")
    match_id = int(parts[1])
    player_id = int(parts[2])
    
    # Уведомляем игрока
    try:
        await bot.send_message(player_id, f"🚫 Администратор аннулировал ваш результат в матче №{match_id} из-за несовпадения никнейма.")
    except: pass
    
    try: await callback.answer(f"Результат игрока {player_id} аннулирован!")
    except TelegramBadRequest: pass
    
    # Обновляем сообщение админа, возвращаясь к основным кнопкам
    await admin_back_to_match(callback, answered=True)

@dp.callback_query(F.data.startswith("admin_back_to_match_"))
async def admin_back_to_match(callback: types.CallbackQuery, answered: bool = False):
    if callback.from_user.id not in ADMINS: return
    match_id = int(callback.data.split("_")[4])
    
    if not answered:
        try: await callback.answer()
        except TelegramBadRequest: pass
    
    # Восстанавливаем оригинальные кнопки
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ CT WIN", callback_data=f"admin_win_{match_id}_ct"),
        types.InlineKeyboardButton(text="✅ T WIN", callback_data=f"admin_win_{match_id}_t")
    )
    builder.row(types.InlineKeyboardButton(text="🚫 Аннулировать одному", callback_data=f"admin_nullone_{match_id}"))
    builder.row(types.InlineKeyboardButton(text="❌ Отменить всем", callback_data=f"admin_cancel_{match_id}"))
    
    await callback.message.edit_caption(
        caption=f"🖼 Результат матча №{match_id}\n\nВыберите победителя или действие:",
        reply_markup=builder.as_markup()
    )
    try: await callback.answer()
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("admin_win_"))
async def admin_confirm_win(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS: return
    
    _, _, match_id, winner_team = callback.data.split("_")
    match_id = int(match_id)
    
    if match_id not in active_matches:
        await callback.answer("Ошибка: матч не найден в активных!", show_alert=True)
        return
        
    match = active_matches[match_id]
    elo_gain = match['elo_gain']
    
    # Начисляем/вычитаем ELO
    for team_name, players in match['teams'].items():
        is_win = (team_name == winner_team)
        change = elo_gain if is_win else -elo_gain
        for p_uid, p_data in players:
            db.update_elo(p_uid, change, is_win)
            try:
                result_text = "ПОБЕДА! 🎉" if is_win else "ПОРАЖЕНИЕ... 📉"
                await bot.send_message(p_uid, f"🔔 Результат матча №{match_id} подтвержден!\n\nРезультат: {result_text}\nИзменение ELO: {change:+}")
            except: pass
            
    # Синхронизация: удаляем кнопки у всех админов
    if match_id in admin_messages:
        for admin_id, msg_id in admin_messages[match_id].items():
            try:
                await bot.edit_message_caption(
                    chat_id=admin_id,
                    message_id=msg_id,
                    caption=f"✅ Матч №{match_id} подтвержден. Победили {winner_team.upper()}.\n(Подтвердил: {callback.from_user.full_name})"
                )
            except: pass
        del admin_messages[match_id]
        
    if match_id in active_matches:
        del active_matches[match_id]
    try: await callback.answer("Результат подтвержден!")
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("admin_cancel_"))
async def admin_cancel_match(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS: return
    match_id = int(callback.data.split("_")[2])
    
    if match_id in active_matches:
        match = active_matches[match_id]
        for p_uid, _ in match['players']:
            try:
                await bot.send_message(p_uid, f"❌ Результат матча №{match_id} был отклонен админом.")
            except: pass
            
    # Синхронизация: удаляем кнопки у всех админов
    if match_id in admin_messages:
        for admin_id, msg_id in admin_messages[match_id].items():
            try:
                await bot.edit_message_caption(
                    chat_id=admin_id,
                    message_id=msg_id,
                    caption=f"❌ Результат матча №{match_id} отклонен.\n(Отклонил: {callback.from_user.full_name})"
                )
            except: pass
        del admin_messages[match_id]
        
    try: await callback.answer("Результат отклонен")
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("l_exit_"))
async def lobby_exit_callback(callback: types.CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    _, _, mode, lobby_id = callback.data.split("_")
    lobby_id = int(lobby_id)
    user_id = callback.from_user.id
    
    # Пытаемся найти пользователя во всех лобби этого режима, если в указанном его нет
    found = False
    if user_id in lobby_players[mode][lobby_id]:
        del lobby_players[mode][lobby_id][user_id]
        found = True
    else:
        # Проверяем другие лобби этого же режима
        for lid in lobby_players[mode]:
            if user_id in lobby_players[mode][lid]:
                del lobby_players[mode][lid][user_id]
                lobby_id = lid # Обновляем ID для корректного обновления сообщений
                found = True
                break
    
    if found:
        db.remove_lobby_member(user_id)
        await callback.message.answer("❌ Вы вышли из лобби.")
        await update_all_lobby_messages(mode, lobby_id)
        await update_lobby_list_for_all(mode)
    else:
        await callback.answer("Вы не в этом лобби.")

@dp.message(F.text == "Список лидеров 🏆")
async def leaderboard(message: types.Message):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы.")
            return

    top_players = db.get_top_players(10)
    if not top_players:
        await message.answer("Список лидеров пока пуст.", reply_markup=main_menu_keyboard(message.from_user.id))
        return
        
    text = "🏆 1 СЕЗОН: ТОП-10 ИГРОКОВ\n\n"
    for i, (nickname, elo, level) in enumerate(top_players, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {nickname} — {elo} ELO (Lvl {level})\n"
    
    await message.answer(text, reply_markup=main_menu_keyboard(message.from_user.id))

@dp.message(F.text == "Правила 📖")
async def rules(message: types.Message):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы.")
            return

    rules_text = (
        "📖 БАЗОВЫЕ ПРАВИЛА FACEIT (PROJECT EVOLUTION):\n\n"
        "1. 👤 Никнейм в боте ДОЛЖЕН совпадать с никнеймом в игре. За несовпадение — аннулирование результата.\n"
        "2. 📸 После завершения матча капитаны (или игроки) обязаны отправить скриншот результата.\n"
        "3. 🤝 Уважительное отношение к союзникам и противникам. Оскорбления запрещены.\n"
        "4. 🚫 Использование стороннего ПО (читов), багов игры строго запрещено — бан навсегда.\n"
        "5. ⏱ На подтверждение матча дается 60 секунд. Если не успели — вылет из лобби.\n"
        "6. 🚪 Выход посреди матча строго ЗАПРЕЩЕН — бан на 1 час при первом нарушении.\n"
        "7. 🚫 Доджить (пропускать) подтвержденную игру ЗАПРЕЩЕНО — блокировка поиска на 30 минут.\n"
        "8. 👤 Если администрация обнаружит, что ваш никнейм в игре не совпадает с ником в боте, результат матча может быть аннулирован лично для вас.\n"
        "9. ⚠️ Непринятие игры: при получении 3/3 предупреждений — бан на 30 минут.\n\n"
        "📝 ПОДРОБНАЯ ИНСТРУКЦИЯ ПО ИГРЕ:\n"
        "Перед началом игры вам нужно зайти в лобби, после того как все игроки соберутся система автоматически выберет 2 капитанов. Капитаны обоих команд (начиная с CT) должны будут голосовать за бан карт, после этого капитан T начинает первый выбирать игроков в команду. После всего этого появится сообщение с информацией о матче. Если вы капитан CT, то вам нужно будет создавать лобби и приглашать всех (вам будут писать в лс по вашему айди), а если же вы не хостер лобби, то вам нужно будет скопировать айди в таблице с информацией, найти этого игрока в игре и написать точку ему в лс и он вас пригласит. После окончания игры нужно отправить результаты в бота.\n\n"
        "Удачи в игре! 🔥"
    )
    await message.answer(rules_text, reply_markup=main_menu_keyboard(message.from_user.id))

import uvicorn
from app import app as fastapi_app

async def main():
    db.init_db()
    
    # Синхронизация лобби из БД при старте
    lobby_members = db.get_all_lobby_members()
    for mode, lid, uid in lobby_members:
        user = db.get_user(uid)
        if user:
            level = db.get_level_by_elo(user[2])
            lobby_players[mode][lid][uid] = {"nickname": user[1], "level": level, "game_id": user[0]}
    
    logging.info(f"Восстановлено {len(lobby_members)} участников лобби из БД")
    
    # Настройка и запуск FastAPI
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    
    # Запуск бота и сервера параллельно
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

@dp.message(F.text == "Поддержка 🛠️")
async def support_handler(message: types.Message, state: FSMContext):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы в этом боте.")
            return

    # Состояние очищается в мидлвари, но на всякий случай
    await state.clear()
    await state.set_state(SupportState.waiting_for_message)
    await message.answer("Опишите вашу проблему или идею в одном сообщении. 📩\nАдмины рассмотрет ваше обращение и ответят прямо здесь.\n\n_Чтобы отменить, просто нажмите любую кнопку в меню._", parse_mode="Markdown")

@dp.message(SupportState.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext):
    # Фильтруем системные сообщения меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    
    # Если нажата кнопка меню — отменяем обращение
    if message.text in menu_buttons:
        await state.clear()
        # Вызываем хендлер кнопки вручную, чтобы пользователь перешел куда хотел
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    # Если это команда
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    # Проверка на наличие контента
    if not message.text and not message.photo:
        await message.answer("Пожалуйста, отправьте текстовое сообщение или фото.")
        return
        
    ticket_id = db.create_support_ticket(message.from_user.id, message.text or "[Фото]")
    user_data = db.get_user(message.from_user.id)
    nickname = user_data[1] if user_data else "Неизвестно"
    
    # Инициализируем в памяти
    if ticket_id not in support_requests:
        support_requests[ticket_id] = {
            "user_id": message.from_user.id,
            "text": message.text,
            "admin_id": None,
            "messages": {}
        }
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🙋‍♂️ Взять в работу", callback_data=f"sup_take_{ticket_id}"))
    
    admin_text = (
        f"🆘 НОВОЕ ОБРАЩЕНИЕ №{ticket_id}\n"
        f"👤 От: {nickname} (ID: {message.from_user.id})\n\n"
        f"📝 Текст: {message.text or '[Фото]'}"
    )
    
    sent_to_at_least_one = False
    for admin_id in ADMINS:
        try:
            msg = await bot.send_message(admin_id, admin_text, reply_markup=builder.as_markup())
            support_requests[ticket_id]["messages"][admin_id] = msg.message_id
            sent_to_at_least_one = True
        except Exception as e:
            logging.error(f"Failed to send support notification to admin {admin_id}: {e}")
            
    await message.answer(f"✅ Ваше обращение №{ticket_id} успешно отправлено! 📨\nОжидайте ответа администратора.", reply_markup=main_menu_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data.startswith("sup_take_"))
async def handle_support_take(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == callback.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        await callback.answer("❌ Вы заблокированы.", show_alert=True)
        return

    if callback.from_user.id not in ADMINS: return
    
    ticket_id = int(callback.data.split("_")[2])
    
    # Пытаемся получить из памяти
    req = support_requests.get(ticket_id)
    
    # Если в памяти нет (после перезагрузки), пробуем из БД
    if not req:
        ticket_db = db.get_support_ticket(ticket_id)
        if not ticket_db:
            await callback.answer("Обращение не найдено.", show_alert=True)
            return
        
        uid, text, admin_id, status = ticket_db
        if status == 'closed':
            await callback.answer("Это обращение уже закрыто.", show_alert=True)
            return
            
        # Восстанавливаем в памяти
        support_requests[ticket_id] = {
            "user_id": uid,
            "text": text,
            "admin_id": admin_id,
            "messages": {} # Сообщения админов восстановить сложнее, просто работаем с текущим
        }
        req = support_requests[ticket_id]

    if req["admin_id"] is not None:
        await callback.answer(f"Это обращение уже взял админ ID: {req['admin_id']}", show_alert=True)
        return
        
    req["admin_id"] = callback.from_user.id
    db.update_support_ticket(ticket_id, admin_id=callback.from_user.id)
    
    # Обновляем сообщение у всех админов (если они есть в памяти)
    for admin_id, msg_id in req.get("messages", {}).items():
        try:
            status = "✅ Вы взяли в работу" if admin_id == callback.from_user.id else f"🚫 Взял админ ID: {callback.from_user.id}"
            await bot.edit_message_text(
                chat_id=admin_id,
                message_id=msg_id,
                text=f"🆘 ОБРАЩЕНИЕ №{ticket_id}\n{status}\n\n📝 Текст: {req['text']}"
            )
        except: pass
    
    # Если сообщения не в памяти, просто обновляем текущее
    if not req.get("messages"):
        try:
            await callback.message.edit_text(
                text=f"🆘 ОБРАЩЕНИЕ №{ticket_id}\n✅ Вы взяли в работу\n\n📝 Текст: {req['text']}"
            )
        except: pass
        
    await callback.message.answer("Введите ответ игроку: 📝")
    await state.update_data(current_ticket_id=ticket_id)
    await state.set_state(SupportState.waiting_for_admin_reply)
    # Удаляем лишний callback.answer() в конце, так как он уже есть в начале функции

@dp.message(SupportState.waiting_for_admin_reply)
async def process_admin_reply(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    
    # Фильтруем кнопки меню для админа
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    data = await state.get_data()
    ticket_id = data.get("current_ticket_id")
    
    # Проверяем наличие ticket_id
    if ticket_id is None:
        await message.answer("Ошибка: ID тикета не найден в состоянии.")
        await state.clear()
        return

    # Пытаемся получить из памяти или БД
    req = support_requests.get(ticket_id)
    if not req:
        ticket_db = db.get_support_ticket(ticket_id)
        if ticket_db:
            uid, text, admin_id, status = ticket_db
            req = {"user_id": uid, "text": text}
        else:
            await message.answer("Ошибка: обращение не найдено.")
            await state.clear()
            return
            
    user_id = req["user_id"]
    
    try:
        await bot.send_message(
            user_id, 
            f"📩 ОТВЕТ ПО ОБРАЩЕНИЮ №{ticket_id}:\n\n{message.text}\n\n"
            f"👨‍💻 Ответил: {message.from_user.full_name}"
        )
        await message.answer(f"✅ Ответ отправлен игроку (ID: {user_id})")
        # Помечаем в БД как закрытое
        db.update_support_ticket(ticket_id, status='closed')
    except:
        await message.answer("❌ Не удалось отправить сообщение игроку (возможно, бот заблокирован).")
        
    # Удаляем обращение из памяти после ответа
    if ticket_id in support_requests:
        del support_requests[ticket_id]
    await state.clear()

@dp.message(F.text == "Настройки ⚙️")
async def settings_handler(message: types.Message, state: FSMContext):
    # Проверка на бан
    all_users = db.get_all_users()
    user_db_data = next((u for u in all_users if u[0] == message.from_user.id), None)
    if user_db_data and len(user_db_data) > 5 and user_db_data[5] == 1:
        # Проверка временного бана
        ban_until_str = user_db_data[6]
        if ban_until_str:
            ban_until = datetime.strptime(ban_until_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < ban_until:
                await message.answer(f"❌ Вы заблокированы до {ban_until_str}.")
                return
            else:
                db.set_ban_status(message.from_user.id, False)
        else:
            await message.answer("❌ Вы заблокированы в этом боте.")
            return

    # Состояние очищается в мидлвари, но на всякий случай
    await state.clear()
    
    user = db.get_user(message.from_user.id)
    if not user: return
    
    game_id, nickname = user[0], user[1]
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Сменить никнейм ✏️", callback_data="set_nick"))
    builder.row(types.InlineKeyboardButton(text="Сменить ID в игре 🆔", callback_data="set_id"))
    
    text = (
        f"⚙️ НАСТРОЙКИ ПРОФИЛЯ\n\n"
        f"👤 Ваш никнейм: {nickname}\n"
        f"🆔 Ваш ID в игре: {game_id}\n\n"
        f"Выберите, что вы хотите изменить:"
    )
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "set_nick")
async def set_nick_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_new_nickname)
    await callback.message.answer("Введите ваш новый никнейм: ✏️")
    await callback.answer()

@dp.message(SettingsState.waiting_for_new_nickname)
async def process_new_nick(message: types.Message, state: FSMContext):
    # Фильтрация кнопок меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    if not message.text or len(message.text) > 20:
        await message.answer("Никнейм должен быть текстовым и не длиннее 20 символов.")
        return
    
    db.update_user_profile(message.from_user.id, nickname=message.text)
    await message.answer(f"✅ Ваш никнейм успешно изменен на: {message.text}")
    await state.clear()

@dp.callback_query(F.data == "set_id")
async def set_id_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SettingsState.waiting_for_new_game_id)
    await callback.message.answer("Введите ваш новый ID в игре (8-9 цифр): 🆔")
    await callback.answer()

@dp.message(SettingsState.waiting_for_new_game_id)
async def process_new_id(message: types.Message, state: FSMContext):
    # Фильтрация кнопок меню
    menu_buttons = [
        "Профиль 👤", "Поиск матча 🔍", "Список лидеров 🏆", 
        "Правила 📖", "Настройки ⚙️", "Поддержка 🛠️", "Админ-панель 👑"
    ]
    if message.text in menu_buttons:
        await state.clear()
        if message.text == "Профиль 👤": await profile(message)
        elif message.text == "Поиск матча 🔍": await find_match(message)
        elif message.text == "Список лидеров 🏆": await leaderboard(message)
        elif message.text == "Правила 📖": await rules(message)
        elif message.text == "Настройки ⚙️": await settings_handler(message, state)
        elif message.text == "Поддержка 🛠️": await support_handler(message, state)
        elif message.text == "Админ-панель 👑": await admin_panel_handler(message, state)
        return

    if not message.text.isdigit() or not (8 <= len(message.text) <= 9):
        await message.answer("ID должен состоять только из 8-9 цифр.")
        return
    
    db.update_user_profile(message.from_user.id, game_id=message.text)
    await message.answer(f"✅ Ваш игровой ID успешно изменен на: {message.text}")
    await state.clear()

@dp.message(F.text == "Админ-панель 👑")
async def admin_panel_handler(message: types.Message, state: FSMContext):
    # Состояние очищается в мидлвари, но на всякий случай
    await state.clear()
    if message.from_user.id not in ADMINS: return
    
    users = db.get_all_users()
    text = f"👑 АДМИН-ПАНЕЛЬ\nВсего игроков: {len(users)}\n\nВыберите действие:"
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👥 Список игроков", callback_data="admin_users_list_0"))
    # Добавляем другие кнопки, если они были нужны
    
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("admin_users_list_"))
async def admin_users_list_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS: return
    
    page = int(callback.data.split("_")[-1])
    users = db.get_all_users()
    
    # Пагинация по 10 человек
    per_page = 10
    start = page * per_page
    end = start + per_page
    current_users = users[start:end]
    
    text = f"👥 СПИСОК ИГРОКОВ (Страница {page + 1})\n\n"
    builder = InlineKeyboardBuilder()
    
    for u in current_users:
        # Теперь получаем 8 полей из БД (включая missed_games)
        uid, gid, nick, elo, lvl, banned, ban_until, missed_games = u
        status = "✅ Активен"
        if banned:
            if ban_until:
                status = f"🛑 БАН до {ban_until}"
            else:
                status = "🛑 БАН навсегда"
        
        text += f"👤 {nick} (ID: {uid})\n🎮 GameID: {gid} | ELO: {elo} | Lvl: {lvl}\nСтатус: {status}\nПредупреждения: {missed_games}/3\n\n"
        
        if banned:
            builder.row(types.InlineKeyboardButton(text=f"🔓 Разбанить {nick}", callback_data=f"admin_ban_{uid}_0_{page}"))
        else:
            builder.row(
                types.InlineKeyboardButton(text="30м", callback_data=f"admin_ban_{uid}_30m_{page}"),
                types.InlineKeyboardButton(text="1ч", callback_data=f"admin_ban_{uid}_1h_{page}"),
                types.InlineKeyboardButton(text="12ч", callback_data=f"admin_ban_{uid}_12h_{page}"),
                types.InlineKeyboardButton(text="24ч", callback_data=f"admin_ban_{uid}_24h_{page}"),
                types.InlineKeyboardButton(text="∞", callback_data=f"admin_ban_{uid}_inf_{page}")
            )
        builder.row(types.InlineKeyboardButton(text=f"📊 Изменить ELO {nick}", callback_data=f"admin_elo_{uid}"))
        builder.row(types.InlineKeyboardButton(text=f"📈 Изменить Winrate {nick}", callback_data=f"admin_stats_{uid}"))
        builder.row(types.InlineKeyboardButton(text=f"✉️ Написать {nick}", callback_data=f"admin_msg_{uid}"))
    
    # Кнопки навигации
    nav_btns = []
    if page > 0:
        nav_btns.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users_list_{page - 1}"))
    if end < len(users):
        nav_btns.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_users_list_{page + 1}"))
    
    if nav_btns:
        builder.row(*nav_btns)
        
    builder.row(types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_users_list_{page}"))
    
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS: return
    
    parts = callback.data.split("_")
    target_uid = int(parts[2])
    duration_type = parts[3]
    page = int(parts[4])
    
    if duration_type == "0":
        db.set_ban_status(target_uid, False)
        try: await bot.send_message(target_uid, "✅ Администратор разблокировал ваш аккаунт.")
        except: pass
        await callback.answer("Пользователь разблокирован!")
        await admin_users_list_callback(callback)
    else:
        # Сохраняем данные для процесса бана
        until = None
        duration_text = ""
        if duration_type == "30m":
            until = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            duration_text = "на 30 минут"
        elif duration_type == "1h":
            until = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            duration_text = "на 1 час"
        elif duration_type == "12h":
            until = (datetime.now() + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
            duration_text = "на 12 часов"
        elif duration_type == "24h":
            until = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            duration_text = "на 24 часа"
        else:
            duration_text = "навсегда"
            
        await state.update_data(ban_target=target_uid, ban_until=until, ban_duration=duration_text, ban_page=page)
        await state.set_state(AdminAction.waiting_for_ban_reason)
        await callback.message.answer(f"Введите причину бана для игрока (ID: {target_uid}) {duration_text}:")
        await callback.answer()

@dp.message(AdminAction.waiting_for_ban_reason)
async def process_ban_reason(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    target_uid = data['ban_target']
    until = data['ban_until']
    duration = data['ban_duration']
    page = data['ban_page']
    reason = message.text
    
    db.set_ban_status(target_uid, True, until=until)
    
    try:
        ban_msg = f"🛑 Вы были заблокированы {duration}.\nПричина: {reason}"
        if until:
            ban_msg += f"\nБан истекает: {until}"
        await bot.send_message(target_uid, ban_msg)
    except: pass
    
    await message.answer(f"✅ Игрок {target_uid} успешно забанен {duration}.")
    await state.clear()
    
    # Возвращаемся к списку
    users = db.get_all_users()
    # Эмулируем callback для вызова списка
    class FakeCallback:
        def __init__(self, msg, user):
            self.message = msg
            self.from_user = user
        async def answer(self, text=None, show_alert=False): pass
        @property
        def data(self): return f"admin_users_list_{page}"

    await admin_users_list_callback(FakeCallback(message, message.from_user))

@dp.callback_query(F.data.startswith("admin_msg_"))
async def admin_msg_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS: return
    target_uid = int(callback.data.split("_")[2])
    
    await state.update_data(msg_target=target_uid)
    await state.set_state(AdminAction.waiting_for_message_text)
    await callback.message.answer(f"Введите текст сообщения для игрока (ID: {target_uid}):")
    await callback.answer()

@dp.message(AdminAction.waiting_for_message_text)
async def process_admin_message_text(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    target_uid = data['msg_target']
    
    try:
        await bot.send_message(target_uid, f"📩 СООБЩЕНИЕ ОТ АДМИНИСТРАЦИИ:\n\n{message.text}")
        await message.answer(f"✅ Сообщение успешно отправлено игроку {target_uid}.")
    except:
        await message.answer("❌ Не удалось отправить сообщение (возможно, игрок заблокировал бота).")
    
    await state.clear()

@dp.callback_query(F.data.startswith("admin_stats_"))
async def admin_stats_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS: return
    target_uid = int(callback.data.split("_")[2])
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="❌ Убрать поражение", callback_data=f"setstats_{target_uid}_rmloss"),
        types.InlineKeyboardButton(text="➕ Добавить поражение", callback_data=f"setstats_{target_uid}_addloss")
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ Добавить победу", callback_data=f"setstats_{target_uid}_addwin"),
        types.InlineKeyboardButton(text="🚫 Убрать победу", callback_data=f"setstats_{target_uid}_rmwin")
    )
    
    await callback.message.answer(f"Выберите действие со статистикой игрока {target_uid}:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("setstats_"))
async def process_admin_stats_change(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS: return
    
    parts = callback.data.split("_")
    target_uid = int(parts[1])
    action = parts[2]
    
    matches_change = 0
    wins_change = 0
    msg = ""
    
    if action == "rmloss":
        matches_change = -1
        wins_change = 0
        msg = "Удалено 1 поражение"
    elif action == "addloss":
        matches_change = 1
        wins_change = 0
        msg = "Добавлено 1 поражение"
    elif action == "addwin":
        matches_change = 1
        wins_change = 1
        msg = "Добавлена 1 победа"
    elif action == "rmwin":
        matches_change = -1
        wins_change = -1
        msg = "Удалена 1 победа"
        
    db.adjust_user_stats(target_uid, matches_change, wins_change)
    await callback.message.answer(f"✅ Для игрока {target_uid} успешно: {msg}")
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_elo_"))
async def admin_elo_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS: return
    target_uid = int(callback.data.split("_")[2])
    
    await state.update_data(elo_target=target_uid)
    await state.set_state(AdminAction.waiting_for_elo_change)
    await callback.message.answer(f"Введите число, на которое нужно изменить ELO игрока {target_uid} (например, 25 или -25):")
    await callback.answer()

@dp.message(AdminAction.waiting_for_elo_change)
async def process_admin_elo_change(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    
    try:
        elo_change = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 25 или -25).")
        return
        
    data = await state.get_data()
    target_uid = data['elo_target']
    
    db.manual_update_elo(target_uid, elo_change)
    
    # Получаем обновленные данные
    user_data = db.get_user(target_uid)
    new_elo = user_data[2]
    new_lvl = user_data[3]
    
    await message.answer(f"✅ ELO игрока {target_uid} изменено на {elo_change}.\nНовое ELO: {new_elo} | Уровень: {new_lvl}")
    
    try:
        await bot.send_message(target_uid, f"📊 Ваше ELO было изменено администратором на {elo_change}.\nНовое ELO: {new_elo} | Уровень: {new_lvl}")
    except: pass
    
    await state.clear()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
