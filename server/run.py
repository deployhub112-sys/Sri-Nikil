import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import uvicorn

from app import config

if __name__ == '__main__':
    uvicorn.run('main:app', host=config.host(), port=config.port(), log_level='info')
