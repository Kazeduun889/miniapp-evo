import os
import json
import redis.asyncio as redis
from typing import Any
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

async def get_lobby_players(mode, lobby_id):
    key = f"lobby:{mode}:{lobby_id}"
    data = await r.get(key)
    return json.loads(data) if data else {}

async def set_lobby_players(mode, lobby_id, players):
    key = f"lobby:{mode}:{lobby_id}"
    await r.set(key, json.dumps(players))

async def add_player_to_lobby(mode, lobby_id, user_id, player_data):
    players = await get_lobby_players(mode, lobby_id)
    players[str(user_id)] = player_data
    await set_lobby_players(mode, lobby_id, players)

async def remove_player_from_lobby(mode, lobby_id, user_id):
    players = await get_lobby_players(mode, lobby_id)
    if str(user_id) in players:
        del players[str(user_id)]
        await set_lobby_players(mode, lobby_id, players)

async def get_user_current_lobby(user_id):
    for mode in ["1x1", "2x2", "5x5"]:
        for lid in range(1, 11):
            players = await get_lobby_players(mode, lid)
            if str(user_id) in players:
                return {"mode": mode, "id": lid}
    return None

async def get_all_lobbies_data():
    result = {}
    for mode in ["1x1", "2x2", "5x5"]:
        result[mode] = []
        for lid in range(1, 11):
            players = await get_lobby_players(mode, lid)
            result[mode].append({
                "id": lid,
                "players": len(players),
                "max": 2 if mode == "1x1" else (4 if mode == "2x2" else 10)
            })
    return result

# Функции для управления зрителями (те, кто смотрит список лобби или конкретное лобби)
async def set_viewer(user_id, mode, lobby_id, message_id, chat_id):
    key = f"viewer:{user_id}"
    data = {
        "mode": mode,
        "lobby_id": lobby_id,
        "message_id": message_id,
        "chat_id": chat_id
    }
    await r.set(key, json.dumps(data), ex=3600) # Храним 1 час

async def get_viewer(user_id):
    key = f"viewer:{user_id}"
    data = await r.get(key)
    return json.loads(data) if data else None

async def remove_viewer(user_id):
    key = f"viewer:{user_id}"
    await r.delete(key)

async def get_all_viewers():
    keys = await r.keys("viewer:*")
    viewers = {}
    for key in keys:
        try:
            parts = key.split(":")
            if len(parts) < 2: continue
            user_id = parts[1]
            data = await r.get(key)
            if data:
                viewers[int(user_id)] = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            continue
    return viewers

# Универсальные функции для хранения данных в Redis
async def set_data(key: str, data: Any, ex: int = None):
    await r.set(key, json.dumps(data), ex=ex)

async def get_data(key: str) -> Any:
    data = await r.get(key)
    return json.loads(data) if data else None

async def delete_data(key: str):
    await r.delete(key)

async def update_data(key: str, update_dict: dict):
    data = await get_data(key) or {}
    data.update(update_dict)
    await set_data(key, data)

# Специфичные функции для поддержки и матчей
async def set_ticket(ticket_id, data):
    await set_data(f"ticket:{ticket_id}", data, ex=86400) # 24 часа

async def get_ticket(ticket_id):
    return await get_data(f"ticket:{ticket_id}")

async def delete_ticket(ticket_id):
    await delete_data(f"ticket:{ticket_id}")

async def set_match(match_id, data, pending=True):
    prefix = "pending_match" if pending else "active_match"
    await set_data(f"{prefix}:{match_id}", data, ex=3600) # 1 час

async def get_match(match_id, pending=True):
    prefix = "pending_match" if pending else "active_match"
    return await get_data(f"{prefix}:{match_id}")

async def delete_match(match_id, pending=True):
    prefix = "pending_match" if pending else "active_match"
    await delete_data(f"{prefix}:{match_id}")

# Удаляем старые словари и заглушки
# lobby_players и lobby_viewers больше не нужны как переменные, 
# так как мы перешли на асинхронные вызовы Redis.
