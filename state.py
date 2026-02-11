# Глобальное состояние лобби и зрителей
# Структура: {"1x1": {1: {}, ...}, "2x2": {1: {}, ...}, "5x5": {1: {}, ...}}
lobby_players = {
    "1x1": {i: {} for i in range(1, 11)},
    "2x2": {i: {} for i in range(1, 11)},
    "5x5": {i: {} for i in range(1, 11)}
}
# Зрители: {user_id: {"mode": mode, "lobby_id": lid, "message_id": mid, "chat_id": cid}}
lobby_viewers = {} 

# Глобальное состояние активных матчей
active_matches = {}
# Ожидание подтверждения матча
pending_matches = {} # {match_id: {"players": [], "accepted": set(), "messages": {uid: mid}, "mode": mode}}
# История сообщений админов для синхронизации
admin_messages = {} # {match_id: {admin_id: message_id}}
# Состояния поддержки
support_requests = {} # {ticket_id: {"user_id": uid, "text": text, "admin_id": None, "messages": {admin_id: msg_id}}}
