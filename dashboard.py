from flask import Blueprint, render_template, current_app
import os
import time
import sqlite3
import psutil
from utils import file_lock
from db_shared import DB_PATH, get_last_hash, get_last_timestamp

dash_bp = Blueprint('dashboard', __name__, template_folder='templates')

@dash_bp.route("/")
def dashboard():
    db_file = DB_PATH
    db_exists_flag = os.path.exists(db_file)
    db_size = os.path.getsize(db_file) if db_exists_flag else 0
    db_size_mb = round(db_size / (1024 * 1024), 2) if db_exists_flag else 0
    db_hash = get_last_hash() or "N/A"
    db_last_ts = get_last_timestamp() or "N/A"
    user_count = 0
    with file_lock():
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute("SELECT COUNT(*) FROM jwt_login")
            user_count = cur.fetchone()[0]
            conn.close()
        except Exception:
            user_count = "N/A"
    backup_dir = os.path.join(os.path.dirname(db_file), "backups")
    backups = []
    if os.path.exists(backup_dir):
        for f in sorted(os.listdir(backup_dir)):
            path = os.path.join(backup_dir, f)
            if os.path.isfile(path):
                backups.append({
                    'name': f,
                    'size': round(os.path.getsize(path) / (1024 * 1024),2),
                    'mtime': time.ctime(os.path.getmtime(path))
                })
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.2)
    disk = psutil.disk_usage(os.path.dirname(db_file) or '.')
    return render_template(
        "dashboard.html",
        db_file=db_file,
        db_exists_flag=db_exists_flag,
        db_size=db_size,
        db_size_mb=db_size_mb,
        db_hash=db_hash,
        db_last_ts=db_last_ts,
        user_count=user_count,
        backups=backups,
        mem=mem,
        cpu=cpu,
        disk=disk
    )
