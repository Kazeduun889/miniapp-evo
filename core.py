import state
import db
import asyncio
import logging

async def join_lobby(user_id, mode, lobby_id, bot=None):
    user = db.get_user(user_id)
    if not user:
        return {"status": "error", "message": "User not registered"}
    
    lobby = state.lobby_players[mode][lobby_id]
    max_p = 2 if mode == "1x1" else (4 if mode == "2x2" else 10)
    
    if user_id in lobby:
        return {"status": "error", "message": "Already in lobby"}
        
    if len(lobby) >= max_p:
        return {"status": "error", "message": "Lobby full"}
    
    # Check if in another lobby
    for m in state.lobby_players:
        for lid in state.lobby_players[m]:
            if user_id in state.lobby_players[m][lid]:
                del state.lobby_players[m][lid][user_id]
                db.remove_lobby_member(user_id)
                # We should notify bot to update messages here, but we'll do it via a callback or event
    
    level = user[3] # Assuming index 3 is level
    state.lobby_players[mode][lobby_id][user_id] = {"nickname": user[1], "level": level, "game_id": user[0]}
    db.add_lobby_member(mode, lobby_id, user_id)
    
    if len(state.lobby_players[mode][lobby_id]) >= max_p:
        # Trigger match creation (this needs to be handled carefully to avoid circular deps)
        # We'll use a task for this
        return {"status": "success", "action": "joined", "full": True}
    
    return {"status": "success", "action": "joined", "full": False}

async def leave_lobby(user_id, mode, lobby_id):
    lobby = state.lobby_players[mode][lobby_id]
    if user_id in lobby:
        del lobby[user_id]
        db.remove_lobby_member(user_id)
        return {"status": "success", "action": "left"}
    return {"status": "error", "message": "Not in lobby"}
