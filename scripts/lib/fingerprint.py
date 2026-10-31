"""Fingerprint a running stack's records through its read-only API.

    python3 scripts/lib/fingerprint.py <api-base>            -> full JSON (synthetic data only)
    python3 scripts/lib/fingerprint.py <api-base> --digest   -> sha256 and counts only

Use --digest for real records: it prints no values, names or dates.
"""
import hashlib
import json
import sys
import urllib.request

api = sys.argv[1]
get = lambda p: urllib.request.urlopen(api + p).read()
state = {
    "documents": json.loads(get("/documents")),
    "observations": json.loads(get("/observations")),
    "flags_open": json.loads(get("/flags?status=open")),
    "flags_resolved": json.loads(get("/flags?status=resolved")),
    "calc_inputs": json.loads(get("/calculation-inputs/observations")),
    "overview": json.loads(get("/overview")),
}
state["originals"] = {d["id"]: hashlib.sha256(get(f"/documents/{d['id']}/original")).hexdigest()
                      for d in state["documents"]}
state["audit"] = {o["id"]: json.loads(get(f"/observations/{o['id']}"))["audit"] for o in state["observations"]}
for d in state["documents"]:
    assert state["originals"][d["id"]] == d["sha256"], "stored original does not match its recorded hash"
text = json.dumps(state, sort_keys=True)
if "--digest" in sys.argv[2:]:
    print(json.dumps({"sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "observations": len(state["observations"]), "documents": len(state["documents"])}))
else:
    print(text)
