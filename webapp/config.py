import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "web_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_USERNAME = os.getenv("WEB_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "Lead123456@")
TOKEN_TTL_SECONDS = int(os.getenv("WEB_TOKEN_TTL", "7200"))
DEFAULT_BEARER_TOKEN = os.getenv("UDEMY_BEARER", "")

HISTORY_FILE = DATA_DIR / "history.json"
HISTORY_LIMIT = 10

KEYFILE_PATH = BASE_DIR / "keyfile.json"
MAIN_SCRIPT = BASE_DIR / "main.py"
DEFAULT_OUTPUT_DIR = BASE_DIR / "out_dir"
