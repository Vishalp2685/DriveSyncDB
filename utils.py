import os
import threading
import logging
import portalocker
from contextlib import contextmanager

LOCK_FILE = 'temp/lock/db.lock'
LOG_FILE = 'temp/logs/app.log'

os.makedirs("temp/lock", exist_ok=True)
os.makedirs("temp/logs", exist_ok=True)

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

# Exponential backoff
import time

def exponential_backoff(retries):
    delay = min(2 ** retries, 60)
    log_info(f'Waiting {delay}s before retry...')
    time.sleep(delay)
