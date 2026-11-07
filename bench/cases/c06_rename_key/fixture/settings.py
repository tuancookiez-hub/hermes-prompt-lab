import json
from pathlib import Path

_CFG = json.loads((Path(__file__).parent / "config.json").read_text())

HOST = _CFG["host"]
PORT = _CFG["port"]
TIMEOUT = _CFG["timeout"]
RETRIES = _CFG["retries"]
