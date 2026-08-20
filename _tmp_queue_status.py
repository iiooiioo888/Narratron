import json
from collections import Counter

with open(r"data/charpasses/.characteros-queue.json", encoding="utf-8") as f:
    q = json.load(f)

tasks = [t for t in q["tasks"] if t.get("core_id") == 1]
print("Status:", Counter(t.get("status") for t in tasks))

def review(t):
    rm = t.get("result_metadata") or {}
    ig = rm.get("image_generation") or {}
    return (ig.get("review") or {}).get("status") or ig.get("review_status") or rm.get("review_status") or ""

ready = [t for t in tasks if t.get("status") == "ready"]
print("Ready tasks:", [(t["id"], review(t), (t.get("evolution_params") or {}).get("_image_request", {}).get("phase"), (t.get("evolution_params") or {}).get("_image_request", {}).get("age")) for t in ready[:10]])
print("Ready count:", len(ready))
print("Accepted:", sum(1 for t in tasks if review(t) == "accepted"))

blocked = [t for t in ready if review(t) in ("", "pending")]
print("Blocking ready:", [(t["id"], review(t)) for t in blocked[:5]])
