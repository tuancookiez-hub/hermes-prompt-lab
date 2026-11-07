import random, subprocess, sys, time
sys.path.insert(0, ".")
import report
random.seed(1)
orders = [{"customer": f"c{random.randint(0, 6000)}", "amount": random.randint(1, 99)} for _ in range(30000)]
t = time.time(); out = report.build_report(orders); dt = time.time() - t
seen, tot = [], {}
for o in orders:
    if o["customer"] not in tot:
        seen.append(o["customer"]); tot[o["customer"]] = 0
    tot[o["customer"]] += o["amount"]
assert out == "\n".join(f"{c}: {tot[c]}" for c in seen), "output changed"
assert dt < 0.5, f"too slow: {dt:.2f}s"
assert subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "bench.py"]).returncode == 0, "bench.py modified"
