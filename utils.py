import os
import threading
import logging
import portalocker
import platform
from contextlib import contextmanager
import sqlite3
import time

tmp_PATH = os.path.join(os.path.dirname(__file__), 'temp') if platform.system() == 'Windows' else '/tmp/Drive_temp'

LOCK_FILE = os.path.join(tmp_PATH,'db.lock')
LOG_FILE = os.path.join(tmp_PATH,'app.log')

os.makedirs(os.path.dirname(LOCK_FILE),exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE),exist_ok=True)

# Setup logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

def log_info(msg):
    print(msg)
    logging.info(msg)

def log_error(msg):
    print(msg)
    logging.error(msg)

@contextmanager
def file_lock(lock_file=LOCK_FILE):
    """Context manager for file-based locking."""
    with open(lock_file, 'w') as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            yield
        finally:
            portalocker.unlock(lock_fd)

def exponential_backoff(retries):
    delay = min(2 ** retries, 60)
    log_info(f'Waiting {delay}s before retry...')
    time.sleep(delay)

def get_sqlite_connection(db_path):
    """Get a SQLite connection with WAL mode enabled."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        conn.execute('PRAGMA journal_mode=WAL;')
    except Exception as e:
        log_error(f"Failed to set WAL mode: {e}")
    return conn
