from flask import Flask, request, jsonify, render_template, current_app
import os
import sqlite3
from db_manager import db_exists, validate_sqlite_db, restore_from_backup, create_empty_db, calculate_db_hash, rotate_local_backups
from drive_utils import download_latest_db_from_drive, perform_backup
from utils import log_info, log_error, file_lock
import time
import gzip
import psutil
import jwt
from datetime import datetime, timedelta
import bcrypt
from db_shared import get_last_hash, set_last_hash, get_last_timestamp, set_last_timestamp
import platform
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
REQUIRED_TABLES = ['jwt_login']  # Set to a list of required tables if needed
SCHEMA_SQL = None  # Optionally provide SQL schema for new DB
tmp_PATH = os.path.join(os.path.dirname(__file__), 'temp') if platform.system() == 'Windows' else '/tmp/Drive_temp'
DB_PATH = os.path.join(tmp_PATH,'db_1.sqlite') 
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
# Compression helper
def compress_file(src, dst):
    with open(src, 'rb') as f_in, gzip.open(dst, 'wb') as f_out:
        f_out.writelines(f_in)

# Initialization logic
@app.route('/init_db',methods = ['GET'])
def initialize_db():
    if not db_exists(DB_PATH):
        log_info("Local DB not found. Trying to fetch from Google Drive...")
        drive_path = download_latest_db_from_drive(DB_PATH)
        if drive_path and validate_sqlite_db(DB_PATH, REQUIRED_TABLES):
            log_info("DB downloaded and validated.")
            return jsonify({"db downloaded and validated"})
        else:
            log_info("Drive fetch failed or DB invalid. Creating new empty DB.")
            create_empty_db(DB_PATH, SCHEMA_SQL)
            return jsonify({"Created_empty db"})
    else:
        if not validate_sqlite_db(DB_PATH, REQUIRED_TABLES):
            log_info("Local DB invalid. Attempting repair/restore from backup...")
            if restore_from_backup(DB_PATH) and validate_sqlite_db(DB_PATH, REQUIRED_TABLES):
                log_info("Repair successful.")
            else:
                log_info("Repair failed. Trying to fetch from Google Drive...")
                drive_path = download_latest_db_from_drive(DB_PATH)
                if drive_path and validate_sqlite_db(DB_PATH, REQUIRED_TABLES):
                    log_info("DB downloaded and validated.")
                else:
                    log_info("Drive fetch failed or DB invalid. Creating new empty DB.")
                    create_empty_db(DB_PATH, SCHEMA_SQL)

# JWT authentication
JWT_SECRET = os.getenv('JWT_SECRET')
JWT_ALGORITHM = 'HS256'
JWT_EXP_DELTA_SECONDS = 3600  # 1 hour

# JWT helper functions
def generate_jwt(payload):
    payload = payload.copy()
    payload['exp'] = datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# JWT login route
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Missing username or password'}), 400
    try:
        with file_lock():
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute('SELECT password FROM jwt_login WHERE username=?', (username,))
            row = cur.fetchone()
            if row:
                stored_hash = row[0]
                if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                    token = generate_jwt({'username': username})
                    return jsonify({'token': token})
            return jsonify({'error': 'Invalid credentials'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# JWT decorator
def require_jwt(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', None)
        if not auth or not auth.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid JWT'}), 401
        token = auth.split(' ', 1)[1]
        payload = decode_jwt(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired JWT'}), 401
        request.jwt_payload = payload
        return func(*args, **kwargs)
    return wrapper

# API Endpoints
@app.route('/query', methods=['POST'])
@require_jwt
def query():
    data = request.get_json()
    sql = data.get('sql')
    if not sql:
        return jsonify({'error': 'Missing SQL query'}), 400
    is_write = sql.strip().split()[0].lower() in {'insert', 'update', 'delete', 'replace', 'create', 'drop', 'alter'}
    try:
        with file_lock():
            conn = sqlite3.connect(DB_PATH)
            if is_write:
                conn.execute('BEGIN')
                try:
                    conn.execute(sql)
                    conn.commit()
                    new_hash = calculate_db_hash(DB_PATH)
                    last_hash = get_last_hash()
                    if new_hash != last_hash:
                        set_last_hash(new_hash)
                        set_last_timestamp(time.time())
                        # Optionally compress before upload
                        compressed = DB_PATH + '.gz'
                        compress_file(DB_PATH, compressed)
                        perform_backup(DB_PATH)   # You can modify perform_backup to use compressed if desired
                        os.remove(compressed)
                        log_info('Backup and sync complete.')
                    return jsonify({'status': 'success', 'hash': new_hash})
                except Exception as e:
                    conn.rollback()
                    log_error(f"Write failed:  {e}")
                    return jsonify({'error': str(e)}), 400
            else:
                cur = conn.execute(sql)
                rows = cur.fetchall()
                return jsonify({'result': rows})
    except Exception as e:
        log_error(f"Query error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    if db_exists(DB_PATH) and validate_sqlite_db(DB_PATH, REQUIRED_TABLES):
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'}), 500

@app.route('/backup', methods=['POST'])
@require_jwt
def backup():
    try:
        perform_backup(DB_PATH)
        return jsonify({'status': 'backup complete'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Restore endpoint
@app.route('/restore', methods=['POST'])
@require_jwt
def restore():
    try:
        if restore_from_backup(DB_PATH):
            set_last_hash(calculate_db_hash(DB_PATH))
            set_last_timestamp(time.time())
            return jsonify({'status': 'restored from backup'})
        else:
            return jsonify({'error': 'No backup available'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Conflict check endpoint
@app.route('/conflict', methods=['GET'])
@require_jwt
def conflict():
    # For demo: just return last timestamp and hash
    return jsonify({
        'last_hash': get_last_hash(),
        'last_timestamp': get_last_timestamp()
    })

@app.route('/memstatus', methods=['GET'])
def memstatus():
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    disk = psutil.disk_usage(os.path.dirname(DB_PATH) or '.')
    return jsonify({
        'ram': {
            'total': mem.total,
            'available': mem.available,
            'percent': mem.percent,
            'used': mem.used,
            'free': mem.free
        },
        'cpu': {
            'percent': cpu
        },
        'disk': {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': disk.percent
        }
    })

# Ensure at least one default user exists for JWT login
@app.route('/create_jwt_table',methods = ['GET'])
def ensure_jwt_login_table():
    with file_lock():
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS jwt_login (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    return "table created"

@app.route('/create_login',methods = ['GET'])
def ensure_default_user():
    default_username = os.getenv('JWT_ADMIN_USERNAME')
    default_password = os.getenv('JWT_ADMIN_PASSWORD')
    with file_lock():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT * FROM jwt_login WHERE username=?", (default_username,))
        if not cur.fetchone():
            hashed_pw = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            conn.execute(
                "INSERT INTO jwt_login (username, password) VALUES (?,?)",
                (default_username, hashed_pw)
            )
            conn.commit()
            conn.close()
            log_info(f"Default user created: {default_username}")
            return "Default created"
        else:
            log_info(f"Default user already exists: {default_username}")
            conn.close()
            return "default already exist"

# Dashboard route (was blueprint, now direct route)
@app.route("/")
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

@app.route('/logs', methods=['GET'])
def get_logs():
    log_path = os.path.join(os.path.dirname(DB_PATH), 'app.log')
    if not os.path.exists(log_path):
        return jsonify({'error': 'Log file not found'}), 404
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    # Optionally, limit the log size returned
    max_chars = 10000
    if len(content) > max_chars:
        content = content[-max_chars:]
    return ('<pre>' + content + '</pre>')


# Main entry
if __name__ == "__main__":
    initialize_db()
    ensure_jwt_login_table()
    ensure_default_user()
    app.run(debug=True)
