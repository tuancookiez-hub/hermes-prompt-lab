"""Builds the weekly customer report."""


def unique_customers(orders):
    seen = []
    for o in orders:
        if o["customer"] not in seen:
            seen.append(o["customer"])
    return seen


def build_report(orders):
    customers = unique_customers(orders)
    lines = []
    for c in customers:
        total = sum(o["amount"] for o in orders if o["customer"] == c)
        lines.append(f"{c}: {total}")
    return "\n".join(lines)
