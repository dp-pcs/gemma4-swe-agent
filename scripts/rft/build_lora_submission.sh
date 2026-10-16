#!/usr/bin/env bash
# Build a competition submission zip from a prompt tree + packaged PEFT adapter.
#   build_lora_submission.sh PROMPT_TREE ADAPTER_DIR OUT_DIR [ADAPTER_NAME]
# Writes OUT_DIR/source (tree with adapters/<name>/ and `adapter: <name>`), OUT_DIR/submission.zip,
# OUT_DIR/provenance.json and runs the pinned-SDK compile check when /tmp/cc_venv exists.
set -euo pipefail
TREE=$1; ADAPTER=$2; OUT=$3; NAME=${4:-swe_rft_h1}
HERE=$(cd "$(dirname "$0")" && pwd)
[ -e "$OUT" ] && { echo "$OUT exists; use a fresh directory" >&2; exit 1; }
python3 -I "$HERE/make_lora_arm.py" "$TREE" "$ADAPTER" "$OUT/source" --name "$NAME"
find "$OUT/source" -name '._*' -delete
( cd "$OUT/source" && COPYFILE_DISABLE=1 zip -q -r -X ../submission.zip . )
SIZE=$(stat -f%z "$OUT/submission.zip" 2>/dev/null || stat -c%s "$OUT/submission.zip")
UNPACKED=$(find "$OUT/source" -type f -exec stat -f%z {} + 2>/dev/null | awk '{s+=$1} END {print s}')
[ "${UNPACKED:-0}" -lt 3221225472 ] || { echo "unpacked size $UNPACKED exceeds 3 GiB" >&2; exit 1; }
SHA=$(shasum -a 256 "$OUT/submission.zip" | cut -d' ' -f1)
python3 -I - "$OUT" "$TREE" "$ADAPTER" "$NAME" "$SHA" "$SIZE" "$UNPACKED" <<'EOF'
import json, sys, hashlib, datetime, zipfile
out, tree, adapter, name, sha, size, unpacked = sys.argv[1:8]
with zipfile.ZipFile(f"{out}/submission.zip") as z:
    members = sorted(z.namelist())
json.dump({
    "built_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "prompt_tree": tree, "adapter_dir": adapter, "adapter_name": name,
    "zip_sha256": sha, "zip_bytes": int(size), "unpacked_bytes": int(unpacked),
    "members": members,
}, open(f"{out}/provenance.json", "w"), indent=2)
print(f"zip {size} bytes, unpacked {unpacked} bytes, sha256 {sha[:16]}…, {len(members)} members")
EOF
if [ -x /tmp/cc_venv/bin/python ]; then
  /tmp/cc_venv/bin/python -I "$HERE/../compile_check.py" "$OUT/source" > "$OUT/compile_check.json" && \
    python3 -I -c "import json,sys; j=json.load(open(sys.argv[1])); print('compile ok | model', j['model'], '| tools', len(j['tools']), '| sub_agents', j['sub_agents'])" "$OUT/compile_check.json"
fi
