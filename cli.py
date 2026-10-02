"""Command-line use:  python cli.py sample_synopsis.json output.docx"""
import json, sys
try:
    from synopsis.generator import build_document
    from synopsis.validator import validate
except ImportError:
    from generator import build_document
    from validator import validate

src = sys.argv[1] if len(sys.argv) > 1 else "sample_synopsis.json"
out = sys.argv[2] if len(sys.argv) > 2 else "synopsis_output.docx"
data = json.load(open(src, encoding="utf-8"))
for lvl, sec, msg in validate(data):
    print(f"[{lvl.upper():7}] {sec}: {msg}")
build_document(data, out)
print("Saved:", out)
