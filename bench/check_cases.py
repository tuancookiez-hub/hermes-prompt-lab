"""Dev check: every case's checker must FAIL on the fixture and PASS on its reference fix."""
import pathlib, shutil, subprocess, sys, tempfile, yaml
HERE = pathlib.Path(__file__).parent
REF = {
  "c01_fix_tests": {"calc.py": "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('b must not be zero')\n    return a / b\n"},
  "c02_json_flag": {"cli.py": "import argparse, json\n\n\ndef total(values):\n    return sum(values)\n\n\ndef main(argv=None):\n    p = argparse.ArgumentParser()\n    p.add_argument('values', nargs='+', type=int)\n    p.add_argument('--json', action='store_true')\n    a = p.parse_args(argv)\n    print(json.dumps({'total': total(a.values)}) if a.json else f'Total: {total(a.values)}')\n\n\nif __name__ == '__main__':\n    main()\n"},
  "c03_faster_report": {"report.py": "def build_report(orders):\n    totals = {}\n    for o in orders:\n        totals[o['customer']] = totals.get(o['customer'], 0) + o['amount']\n    return chr(10).join(f'{c}: {t}' for c, t in totals.items())\n"},
  "c04_clean_entries": None,
  "c05_parse_dates": {"utils/dates.py": "import datetime as dt\n\n\ndef format_date(d):\n    return d.strftime('%d/%m/%Y')\n\n\ndef parse_date(s):\n    return dt.datetime.strptime(s, '%d/%m/%Y').date()\n"},
  "c06_rename_key": {"config.json": '{"host": "localhost", "port": 8080, "timeout_seconds": 30, "retries": 3}\n',
                     "settings.py": "import json\nfrom pathlib import Path\n_CFG = json.loads((Path(__file__).parent / 'config.json').read_text())\nHOST=_CFG['host']\nPORT=_CFG['port']\nTIMEOUT=_CFG['timeout_seconds']\nRETRIES=_CFG['retries']\n"},
}
def run(case_dir, d):
    r = subprocess.run([sys.executable, str(case_dir / "check.py")], cwd=d, capture_output=True, text=True)
    if r.returncode and "-v" in sys.argv: print(r.stderr[-400:])
    return r.returncode == 0
def prep(case_dir, d):
    shutil.copytree(case_dir / "fixture", d, dirs_exist_ok=True)
    for c in (["git", "-c", "core.autocrlf=false", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=b", "-c", "user.email=b@x", "commit", "-qm", "fixture"]):
        subprocess.run(c, cwd=d, check=True)
ok = True
for case_dir in sorted((HERE / "cases").iterdir()):
    spec = yaml.safe_load((case_dir / "case.yaml").read_text())
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        prep(case_dir, a); prep(case_dir, b)
        if spec["id"] == "c04_clean_entries":
            import json
            p = pathlib.Path(b) / "data/entries.json"; e = json.loads(p.read_text())
            p.write_text(json.dumps([x for x in e if x["date"] >= "2026-01-01" or x["pinned"]], indent=2))
        else:
            for rel, txt in REF[spec["id"]].items():
                (pathlib.Path(b) / rel).write_text(txt)
        before, after = run(case_dir, a), run(case_dir, b)
        good = (not before) and after
        ok &= good
        print(f"{spec['id']:20} fixture_fails={not before} reference_passes={after} {'OK' if good else 'BAD'}")
sys.exit(0 if ok else 1)
