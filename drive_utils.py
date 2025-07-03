# This file will contain all Google Drive related functions, refactored from app.py
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import platform
from utils import log_info, log_error, exponential_backoff

SCOPES = ['https://www.googleapis.com/auth/drive.file']
BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'temp/backups') if platform.system() == 'Windows' else '/tmp/Drive_temp/backups'
MAX_BACKUPS = 3
folder_id = os.getenv('FOLDER_ID')

def get_service_account_info_from_env():
    private_key = os.environ.get("GOOGLE_PRIVATE_KEY")
    if private_key is None:
        raise ValueError("GOOGLE_PRIVATE_KEY environment variable is not set.")
    return {
        "type": os.environ.get("GOOGLE_TYPE"),
        "project_id": os.environ.get("GOOGLE_PROJECT_ID"),
        "private_key_id": os.environ.get("GOOGLE_PRIVATE_KEY_ID"),
        "private_key": private_key.replace('\\n', '\n'),
        "client_email": os.environ.get("GOOGLE_CLIENT_EMAIL"),
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "auth_uri": os.environ.get("GOOGLE_AUTH_URI"),
        "token_uri": os.environ.get("GOOGLE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.environ.get("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.environ.get("GOOGLE_CLIENT_X509_CERT_URL"),
        "universe_domain": os.environ.get("GOOGLE_UNIVERSE_DOMAIN"),
    }

def build_drive_service():
    service_account_info = get_service_account_info_from_env()
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)

def find_drive_file(service, name):
    query = f"name='{name}' and trashed=false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    results = service.files().list(q=query, spaces='drive', fields="files(id, name)").execute()
    items = results.get('files', [])
    return items[0] if items else None

def delete_drive_file(service, filename):
    file = find_drive_file(service, filename)
    if file:
        service.files().delete(fileId=file['id']).execute()
        log_info(f"🗑️ Deleted Drive file: {filename}")

def rename_drive_file(service, old_name, new_name):
    file = find_drive_file(service, old_name)
    if file:
        service.files().update(fileId=file['id'], body={"name": new_name}).execute()
        log_info(f"🔄 Renamed Drive file: {old_name} → {new_name}")

def upload_to_drive(service, file_path, filename):
    file_metadata = {
        'name': filename,
        'parents': [folder_id] if folder_id else []
    }
    media = MediaFileUpload(file_path, resumable=False)
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    log_info(f"☁️ Uploaded to Drive: {filename} (ID: {file['id']})")

def rotate_drive_backups(latest_local_backup_path):
    service = build_drive_service()
    delete_drive_file(service, "db_3.sqlite")
    rename_drive_file(service, "db_2.sqlite", "db_3.sqlite")
    rename_drive_file(service, "db_1.sqlite", "db_2.sqlite")
    upload_to_drive(service, latest_local_backup_path, "db_1.sqlite")

def download_latest_db_from_drive(destination_path='db_1.sqlite'):
    try:
        service = build_drive_service()
        query = f"name='db_1.sqlite' and trashed=false"
        if folder_id:
            query += f" and '{folder_id}' in parents"
        result = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        items = result.get('files', [])
        print(items)
        if not items:
            log_error("❌ No db_1.sqlite found on Drive.")
            return None
        file_id = items[0]['id']
        request = service.files().get_media(fileId=file_id)
        os.makedirs(os.path.dirname(destination_path) or '.', exist_ok=True)
        with open(destination_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                log_info(f"⬇️ Downloading: {int(status.progress() * 100)}%")
        log_info(f"✅ Downloaded DB to: {destination_path}")
        return destination_path
    except Exception as e:
        log_error(f"❌ Failed to download DB: {e}")
        return None

def perform_backup(db_path='db_1.sqlite'):
    from db_manager import rotate_local_backups
    rotate_local_backups(db_path)
    rotate_drive_backups(os.path.join(BACKUP_DIR, "db_1.sqlite"))
