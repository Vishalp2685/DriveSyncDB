import os
import time

def get_db_path():
    # Use /temp/db_1.sqlite on Render, else use env or default
    return os.path.join(os.environ.get('db_name', 'db_1.sqlite'))

DB_PATH = get_db_path()
DB_HASH_PATH = DB_PATH + '.hash'
DB_TIMESTAMP_PATH = DB_PATH + '.ts'
DB_LOCK_PATH = 'db.lock'
APP_LOG_PATH = 'app.log'

def get_last_hash():
    if os.path.exists(DB_HASH_PATH):
        with open(DB_HASH_PATH, 'r') as f:
            return f.read().strip()
    return None

def set_last_hash(h):
    with open(DB_HASH_PATH, 'w') as f:
        f.write(h)

def get_last_timestamp():
    if os.path.exists(DB_TIMESTAMP_PATH):
        with open(DB_TIMESTAMP_PATH, 'r') as f:
            return float(f.read().strip())
    return 0

def set_last_timestamp(ts):
    with open(DB_TIMESTAMP_PATH, 'w') as f:
        f.write(str(ts))
