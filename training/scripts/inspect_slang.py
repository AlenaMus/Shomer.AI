"""Inspect slang_lexicon.json."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
path = ROOT / "server" / "data" / "slang_lexicon.json"

data = json.loads(path.read_text(encoding="utf-8"))
print(f"Slang lexicon: {len(data)} entries")
for k, v in list(data.items())[:15]:
    if isinstance(v, dict):
        meaning = v.get("meaning", v.get("description", ""))
        valence = v.get("valence", "")
        age = v.get("age_group", "")
        print(f"  [{k}] meaning={meaning[:50]} valence={valence} age={age}")
    else:
        print(f"  [{k}]: {str(v)[:80]}")
