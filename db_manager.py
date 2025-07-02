import os
import sqlite3
import shutil
from utils import log_info, log_error

BACKUP_DIR = "/temp/backups"
MAX_BACKUPS = 3
os.makedirs(BACKUP_DIR,exist_ok=True)

def db_exists(db_path):
    return os.path.exists(db_path)

def validate_sqlite_db(path, required_tables=None):
    if not os.path.exists(path):
        log_error("❌ File not found.")
        return False
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = set(name[0] for name in cursor.fetchall())
        if required_tables:
            missing = set(required_tables) - tables
            if missing:
                log_error(f"⚠️ Missing required tables: {missing}")
                return False
        log_info(f"✅ DB is valid. Tables: {tables}")
        return True
    except sqlite3.DatabaseError as e:
        log_error(f"❌ Invalid SQLite DB: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def rotate_local_backups(db_path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    oldest = os.path.join(BACKUP_DIR, f"db_{MAX_BACKUPS}.sqlite")
    if os.path.exists(oldest):
        os.remove(oldest)
    for i in reversed(range(1, MAX_BACKUPS)):
        src = os.path.join(BACKUP_DIR, f"db_{i}.sqlite")
        dst = os.path.join(BACKUP_DIR, f"db_{i+1}.sqlite")
        if os.path.exists(src):
            shutil.copy2(src, dst)
    # Copy current db as db_1
    shutil.copy2(db_path, os.path.join(BACKUP_DIR, "db_1.sqlite"))
    log_info("Local backup rotation complete.")

def restore_from_backup(db_path):
    # Try to restore from the most recent backup
    for i in range(1, MAX_BACKUPS+1):
        backup = os.path.join(BACKUP_DIR, f"db_{i}.sqlite")
        if os.path.exists(backup):
            shutil.copy2(backup, db_path)
            log_info(f"Restored DB from backup: {backup}")
            return True
    log_error("No valid backup found to restore.")
    return False

def create_empty_db(db_path, schema_sql=None):
    conn = sqlite3.connect(db_path)
    if schema_sql:
        conn.executescript(schema_sql)
    conn.close()
    log_info(f"Created new empty DB at {db_path}")

def calculate_db_hash(db_path):
    import hashlib
    BUF_SIZE = 65536
    sha256 = hashlib.sha256()
    with open(db_path, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()
