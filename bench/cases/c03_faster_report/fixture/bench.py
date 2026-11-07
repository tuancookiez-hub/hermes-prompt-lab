import random, time
from report import build_report

random.seed(1)
orders = [{"customer": f"c{random.randint(0, 6000)}", "amount": random.randint(1, 99)} for _ in range(30000)]
t = time.time()
out = build_report(orders)
print(f"{time.time() - t:.2f}s", hash(out))
