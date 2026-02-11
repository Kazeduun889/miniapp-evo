import sqlite3

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            game_id TEXT,
            nickname TEXT,
            elo INTEGER DEFAULT 1000,
            level INTEGER DEFAULT 4,
            matches INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица для хранения матчей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'active',
            mode TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица для участников матчей (в том числе ожидающих подтверждения)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS match_players (
            match_id INTEGER,
            user_id INTEGER,
            accepted INTEGER DEFAULT 0,
            PRIMARY KEY (match_id, user_id)
        )
    ''')

    # Таблица для хранения обращений в поддержку
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            status TEXT DEFAULT 'open',
            admin_id INTEGER
        )
    ''')
    
    # Таблица для лобби (синхронизация участников)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lobby_members (
            mode TEXT,
            lobby_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (mode, lobby_id, user_id)
        )
    ''')

    # Миграция: проверяем наличие колонки level
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'level' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 4')
    if 'is_banned' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
    if 'ban_until' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN ban_until DATETIME')
    if 'missed_games' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN missed_games INTEGER DEFAULT 0')
        
    # Миграция: проверяем наличие колонки admin_id в support_tickets
    cursor.execute("PRAGMA table_info(support_tickets)")
    st_columns = [column[1] for column in cursor.fetchall()]
    if 'admin_id' not in st_columns:
        cursor.execute('ALTER TABLE support_tickets ADD COLUMN admin_id INTEGER')
    
    # Миграция для matches
    cursor.execute("PRAGMA table_info(matches)")
    m_columns = [column[1] for column in cursor.fetchall()]
    if 'mode' not in m_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN mode TEXT')
    if 'created_at' not in m_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN created_at DATETIME')

    # Принудительное обновление всех игроков на 4 уровень, если ELO 1000
    cursor.execute('UPDATE users SET level = 4 WHERE elo = 1000')
        
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, game_id, nickname, elo, level, is_banned, ban_until, missed_games FROM users')
    users = cursor.fetchall()
    conn.close()
    return users

def increment_missed_games(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET missed_games = missed_games + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('SELECT missed_games FROM users WHERE user_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return count

def reset_missed_games(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET missed_games = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def set_ban_status(user_id, status, until=None):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    if status:
        cursor.execute('UPDATE users SET is_banned = 1, ban_until = ? WHERE user_id = ?', (until, user_id))
    else:
        cursor.execute('UPDATE users SET is_banned = 0, ban_until = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def create_match(mode, players_ids):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO matches (status, mode) VALUES ("pending", ?)', (mode,))
    match_id = cursor.lastrowid
    
    for uid in players_ids:
        cursor.execute('INSERT INTO match_players (match_id, user_id) VALUES (?, ?)', (match_id, uid))
        
    conn.commit()
    conn.close()
    return match_id

def accept_match_player(match_id, user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE match_players SET accepted = 1 WHERE match_id = ? AND user_id = ?', (match_id, user_id))
    conn.commit()
    conn.close()

def get_match_players(match_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT mp.user_id, u.nickname, u.elo, u.level, mp.accepted 
        FROM match_players mp
        JOIN users u ON mp.user_id = u.user_id
        WHERE mp.match_id = ?
    ''', (match_id,))
    players = cursor.fetchall()
    conn.close()
    return players # [(user_id, nickname, elo, level, accepted), ...]

def cancel_match(match_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE matches SET status = "cancelled" WHERE id = ?', (match_id,))
    conn.commit()
    conn.close()

def get_pending_match(match_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, mode, status FROM matches WHERE id = ? AND status = "pending"', (match_id,))
    match = cursor.fetchone()
    conn.close()
    return match

def get_level_by_elo(elo):
    if elo <= 500: return 1
    if elo <= 750: return 2
    if elo <= 900: return 3
    if elo <= 1050: return 4
    if elo <= 1200: return 5
    if elo <= 1350: return 6
    if elo <= 1530: return 7
    if elo <= 1750: return 8
    if elo <= 2000: return 9
    return 10

def add_user(user_id, game_id, nickname):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # Убеждаемся, что при добавлении ставим elo 1000 и level 4 (хотя DEFAULT в БД есть, INSERT OR REPLACE может затирать)
    cursor.execute('INSERT OR REPLACE INTO users (user_id, game_id, nickname, elo, level) VALUES (?, ?, ?, 1000, 4)', 
                   (user_id, game_id, nickname))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT game_id, nickname, elo, level, matches, wins FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_top_players(limit=10):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nickname, elo, level FROM users ORDER BY elo DESC LIMIT ?', (limit,))
    players = cursor.fetchall()
    conn.close()
    return players

def update_elo(user_id, elo_change, is_win):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET elo = elo + ?, 
            matches = matches + 1,
            wins = wins + ?
        WHERE user_id = ?
    ''', (elo_change, 1 if is_win else 0, user_id))
    
    # Также обновляем уровень на основе нового ELO
    cursor.execute('SELECT elo FROM users WHERE user_id = ?', (user_id,))
    new_elo = cursor.fetchone()[0]
    new_level = get_level_by_elo(new_elo)
    cursor.execute('UPDATE users SET level = ? WHERE user_id = ?', (new_level, user_id))
    
    conn.commit()
    conn.close()

def manual_update_elo(user_id, elo_change):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET elo = elo + ?
        WHERE user_id = ?
    ''', (elo_change, user_id))
    
    # Also update level based on new ELO
    cursor.execute('SELECT elo FROM users WHERE user_id = ?', (user_id,))
    new_elo = cursor.fetchone()[0]
    new_level = get_level_by_elo(new_elo)
    cursor.execute('UPDATE users SET level = ? WHERE user_id = ?', (new_level, user_id))
    
    conn.commit()
    conn.close()

def adjust_user_stats(user_id, matches_change, wins_change):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET matches = matches + ?,
            wins = wins + ?
        WHERE user_id = ?
    ''', (matches_change, wins_change, user_id))
    conn.commit()
    conn.close()

def create_support_ticket(user_id, text):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO support_tickets (user_id, text) VALUES (?, ?)', (user_id, text))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ticket_id

def get_support_ticket(ticket_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, text, admin_id, status FROM support_tickets WHERE id = ?', (ticket_id,))
    ticket = cursor.fetchone()
    conn.close()
    return ticket

def get_all_tickets():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, user_id, text, status FROM support_tickets WHERE status = "open"')
    tickets = cursor.fetchall()
    conn.close()
    return tickets

def add_lobby_member(mode, lobby_id, user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO lobby_members (mode, lobby_id, user_id) VALUES (?, ?, ?)', (mode, lobby_id, user_id))
    conn.commit()
    conn.close()

def remove_lobby_member(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM lobby_members WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_all_lobby_members():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT mode, lobby_id, user_id FROM lobby_members')
    members = cursor.fetchall()
    conn.close()
    return members

def update_support_ticket(ticket_id, admin_id=None, status=None):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    if admin_id is not None:
        cursor.execute('UPDATE support_tickets SET admin_id = ? WHERE id = ?', (admin_id, ticket_id))
    if status is not None:
        cursor.execute('UPDATE support_tickets SET status = ? WHERE id = ?', (status, ticket_id))
    conn.commit()
    conn.close()

def close_ticket(ticket_id, admin_id):
    update_support_ticket(ticket_id, admin_id=admin_id, status='closed')

def update_user_profile(user_id, nickname=None, game_id=None):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    if nickname:
        cursor.execute('UPDATE users SET nickname = ? WHERE user_id = ?', (nickname, user_id))
    if game_id:
        cursor.execute('UPDATE users SET game_id = ? WHERE user_id = ?', (game_id, user_id))
    conn.commit()
    conn.close()

def get_user_by_nickname(nickname):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE nickname = ?', (nickname,))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None

def get_user_by_game_id(game_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE game_id = ?', (game_id,))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None
