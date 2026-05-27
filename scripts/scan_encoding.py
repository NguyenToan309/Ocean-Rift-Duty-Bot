"""
scan_encoding.py — Quét toàn bộ source code, báo cáo file có:
1. UTF-8 BOM (lỗi PowerShell Set-Content)
2. Double-encoded UTF-8 (mojibake "Ã©", "áº¥", "Ä‘", "á»‹", v.v.)
3. Invalid UTF-8 bytes

Chạy: python scripts/scan_encoding.py
"""
import os
import sys

# Các marker phổ biến khi UTF-8 bị decode bằng Latin-1/cp1252 rồi encode lại UTF-8
MOJIBAKE_MARKERS = [
    "Ã©", "Ã¡", "Ã ", "Ãª", "Ã´", "Ã²", "Ã¬", "Ã¹", "Ã­", "Ã³", "Ãº",
    "áº¥", "áº¯", "áº±", "áº³", "áº­", "áº¿", "á»", "Ä", "Æ",
    "â€™", "â€œ", "â€",
]

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".claude", "dist", "build", "src-legacy", ".EasyOCR",
    "htmlcov", ".pytest_cache",
}
EXCLUDE_FILES = {".env", ".env.bak", "package-lock.json"}
TEXT_EXTENSIONS = {
    ".py", ".ps1", ".sh", ".json", ".md", ".ts", ".tsx",
    ".css", ".html", ".yml", ".yaml", ".ini", ".toml", ".txt", ".bat",
    ".cfg", ".jsx", ".js",
}


def scan():
    issues = {"bom": [], "mojibake": [], "invalid": []}
    for root, dirs, files in os.walk("."):
        # Loại exclude
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        path_norm = root.replace(os.sep, "/")
        if any(f"/{ex}/" in path_norm or path_norm.endswith(f"/{ex}") for ex in EXCLUDE_DIRS):
            continue
        for fname in files:
            if fname in EXCLUDE_FILES:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in TEXT_EXTENSIONS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            has_bom = raw[:3] == b"\xef\xbb\xbf"
            if has_bom:
                issues["bom"].append(path)
                raw = raw[3:]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                issues["invalid"].append(path)
                continue
            hits = [m for m in MOJIBAKE_MARKERS if m in text]
            if hits:
                issues["mojibake"].append((path, hits[:5]))
    return issues


def main():
    issues = scan()
    print(f"\n=== Files có BOM ({len(issues['bom'])}):")
    for p in issues["bom"]:
        print(f"  {p}")
    print(f"\n=== Files có MOJIBAKE ({len(issues['mojibake'])}):")
    for p, hits in issues["mojibake"]:
        print(f"  {p}  →  markers: {hits}")
    print(f"\n=== Files INVALID UTF-8 ({len(issues['invalid'])}):")
    for p in issues["invalid"]:
        print(f"  {p}")
    total = len(issues["bom"]) + len(issues["mojibake"]) + len(issues["invalid"])
    print(f"\nTổng: {total} file có vấn đề encoding.")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
