import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], capture_output=True, text=True)
assert r.returncode == 0, r.stdout[-500:]
d = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "tests"])
assert d.returncode == 0, "tests were modified"
