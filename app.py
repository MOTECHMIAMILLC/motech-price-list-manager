from pathlib import Path
import base64
import hashlib
import lzma

PAYLOAD_DIR = Path(__file__).resolve().parent / "mvp_payload"
parts = []
for i in range(1, 6):
    p = PAYLOAD_DIR / f"chunk{i}.txt"
    if not p.exists():
        raise RuntimeError(f"Missing application payload: {p.name}")
    parts.append(p.read_text(encoding="utf-8").strip())

source = lzma.decompress(base64.b64decode("".join(parts))).decode("utf-8")
expected_sha256 = "836399f50ac828bd7f529ec3bc192b7df38e265490bab3ed2d51fa027f883172"
actual_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
if actual_sha256 != expected_sha256:
    raise RuntimeError("Application payload integrity check failed.")

exec(compile(source, "Motech_Price_List_Manager.py", "exec"), globals(), globals())
