"""Dev-only: run the real /promptlab command through the Hermes CLI on sample requests."""
import json, pathlib, shutil, subprocess, sys, tempfile, time
HERE = pathlib.Path(__file__).resolve().parent
HERMES = shutil.which("hermes")
C = HERE / "cases"
SAMPLES = [
    ("make the report faster", C / "c03_faster_report/fixture"),
    ("clean up the old entries", C / "c04_clean_entries/fixture"),
    ("add a function to parse the dates", C / "c05_parse_dates/fixture"),
    ("rename the config key like we discussed", C / "c06_rename_key/fixture"),
    ("ok so the login page is kinda broken on mobile i think the button goes off screen and also can you make the error message nicer, dont touch the backend tho", None),
    ("tolong buat ringkasan laporan jualan bulan lepas dan hantar dalam bentuk jadual", None),
]
for text, cwd in SAMPLES:
    d = tempfile.mkdtemp(prefix="pl-live-")
    if cwd:
        shutil.copytree(cwd, d, dirs_exist_ok=True)
    q = pathlib.Path(d) / ".q.txt"
    q.write_text("/promptlab " + text, encoding="utf-8")
    t = time.time()
    r = subprocess.run([HERMES, "-p", "plbench", "chat", "--query-file", str(q), "--format", "stream-json",
                        "--source", "tool", "--in", d], cwd=d, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=280)
    res = next((json.loads(l) for l in reversed(r.stdout.splitlines()) if '"type": "result"' in l), {})
    print(f"=== {text[:80]}  ({time.time()-t:.0f}s wall, exit {res.get('exit_code')})\n{res.get('text') or res.get('error')}\n", flush=True)
    shutil.rmtree(d, ignore_errors=True)
