import json, sys
sys.path.insert(0, ".")
c = json.load(open("config.json"))
assert "timeout" not in c and c.get("timeout_seconds") == 30 and c["retries"] == 3, c
import settings
assert settings.TIMEOUT == 30
