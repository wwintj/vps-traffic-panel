import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8088))
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "admin")
INTERFACE = os.getenv("INTERFACE", "")
