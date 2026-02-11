from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import db
import os
from typing import Optional

app = FastAPI()

# Настройка путей для шаблонов и статики
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates_path = os.path.join(BASE_DIR, "templates")
static_path = os.path.join(BASE_DIR, "static")

# Создаем директории, если их нет
if not os.path.exists(static_path):
    os.makedirs(static_path)
if not os.path.exists(templates_path):
    os.makedirs(templates_path)

app.mount("/static", StaticFiles(directory=static_path), name="static")
templates = Jinja2Templates(directory=templates_path)

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # game_id, nickname, elo, level, matches, wins
    return {
        "game_id": user[0],
        "nickname": user[1],
        "elo": user[2],
        "level": user[3],
        "matches": user[4],
        "wins": user[5]
    }

@app.get("/api/leaderboard")
async def get_leaderboard():
    users = db.get_all_users()
    # Sort by ELO descending
    sorted_users = sorted(users, key=lambda x: x[3], reverse=True)
    
    leaderboard = []
    for u in sorted_users[:50]: # Top 50
        leaderboard.append({
            "user_id": u[0],
            "nickname": u[2],
            "elo": u[3],
            "level": u[4]
        })
    return leaderboard

@app.get("/api/lobbies/{user_id}")
async def get_lobbies(user_id: int):
    import state
    lobby_players = state.lobby_players
    
    # Проверяем, в каком лобби сейчас пользователь
    user_current_lobby = None
    for mode in ["1x1", "2x2", "5x5"]:
        for lid in range(1, 11):
            if user_id in lobby_players[mode][lid]:
                user_current_lobby = {"mode": mode, "id": lid}
                break
        if user_current_lobby: break

    result = {"modes": {}, "user_lobby": user_current_lobby}
    for mode in ["1x1", "2x2", "5x5"]:
        result["modes"][mode] = []
        for lid in range(1, 11):
            players = lobby_players[mode][lid]
            max_p = 2 if mode == "1x1" else (4 if mode == "2x2" else 10)
            result["modes"][mode].append({
                "id": lid,
                "players": len(players),
                "max": max_p,
                "is_user_here": user_id in players
            })
    return result

@app.post("/api/user/update")
async def update_user(data: dict):
    user_id = data.get("user_id")
    nickname = data.get("nickname")
    game_id = data.get("game_id")
    
    import db
    db.update_user_profile(user_id, nickname=nickname, game_id=game_id)
    return {"status": "success"}

@app.post("/api/lobby/enter")
async def enter_lobby(data: dict):
    user_id = data.get("user_id")
    mode = data.get("mode")
    lobby_id = data.get("lobby_id")
    
    import core
    # Try to join
    result = await core.join_lobby(user_id, mode, lobby_id)
    
    if result["status"] == "error" and result["message"] == "Already in lobby":
        # If already in, then leave (toggle behavior)
        result = await core.leave_lobby(user_id, mode, lobby_id)
        
    return result
