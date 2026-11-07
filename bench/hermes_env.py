"""Dev-only: make Hermes's modules importable for bench scripts. Not shipped as part of the plugin.

Run with Hermes's own Python: tools/python-*/python.exe -I. This never imports hermes_bootstrap,
because that can start a pending dependency build.
"""
import glob, os, sys

HOME = os.environ.get("HERMES_HOME") or os.path.join(os.environ["LOCALAPPDATA"], "hermes")
os.environ["HERMES_HOME"] = HOME
sites = glob.glob(os.path.join(HOME, "installs", "*", "environments", "*", "venv", "Lib", "site-packages"))
if not sites:
    sys.exit("No Hermes dependency environment found.")
sys.path.insert(0, max(sites, key=os.path.getmtime))
sys.path.insert(0, os.environ.get("HERMES_REPO", os.path.join(HOME, "hermes-agent")))
