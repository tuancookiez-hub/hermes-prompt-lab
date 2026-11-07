import json, subprocess, sys
a = subprocess.run([sys.executable, "cli.py", "--json", "2", "3"], capture_output=True, text=True).stdout
b = subprocess.run([sys.executable, "cli.py", "2", "3"], capture_output=True, text=True).stdout.strip()
assert json.loads(a) == {"total": 5}, a
assert b == "Total: 5", b
