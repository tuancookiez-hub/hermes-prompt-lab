import json
e = json.load(open("data/entries.json"))
ids = sorted(x["id"] for x in e)
assert ids == [2, 5, 6, 7, 8, 9], ids
