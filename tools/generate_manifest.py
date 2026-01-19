import json
import hashlib
import os
import glob

manifest = {}
test_dir = "tests/nip011"
pattern = os.path.join(test_dir, "nip011_*.json")

for filepath in glob.glob(pattern):
    if "manifest" in filepath: continue
    basename = os.path.basename(filepath)
    with open(filepath, 'rb') as f:
        content = f.read()
        sha = hashlib.sha256(content).hexdigest()
    
    with open(filepath, 'r') as f:
        try:
            data = json.load(f)
            # Support both 'id' and 'name' as test identifiers
            test_ids = []
            for t in data:
                if isinstance(t, dict):
                    test_id = t.get('id') or t.get('name')
                    if test_id:
                        test_ids.append(test_id)
        except:
            test_ids = []
            
    manifest[basename] = {
        "sha256": sha,
        "test_ids": sorted(test_ids),
        "count": len(test_ids)
    }

# Hash core source files
source_files = [
    "noe/operator_lexicon.py",
    "noe/tokenize.py",
    "noe/noe_validator.py"
]

manifest["sources"] = {}
for src in source_files:
    if os.path.exists(src):
        with open(src, 'rb') as f:
            manifest["sources"][os.path.basename(src)] = hashlib.sha256(f.read()).hexdigest()
    else:
        print(f"Warning: Source file {src} not found")

with open(os.path.join(test_dir, "nip011_manifest.json"), 'w') as f:
    json.dump(manifest, f, indent=4)

print("Manifest generated.")
