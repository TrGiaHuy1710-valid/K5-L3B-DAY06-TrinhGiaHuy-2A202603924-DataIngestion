"""Kiểm chứng bộ benchmark: evidence có tồn tại nguyên văn ở trang gold của PDF không.

Chạy:  python -I scripts/verify_benchmark.py
Kiểm tra:
  1. Mỗi evidence_quote (và alt_gold) xuất hiện trong văn bản trang gold_page.
  2. Số câu >= 20, split >= 15 dev / >= 5 test, >= 3 câu filter, >= 1 câu filter thuộc test.
  3. ID duy nhất; question không chứa gold_page / source id (không rò đáp án vào query).
  4. Câu filter: gold nằm ở trang "thuần" của section được lọc.
  5. Thống kê số trang khác chứa cùng quote (đối chiếu nhiễu / nhiều trang hợp lệ).
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data" / "benchmark_questions.json"

# Trang thuần theo section (trang 3 và 20 là trang chuyển mục)
PURE_PAGES = {
    "A": {1, 2},
    "B.I": set(range(4, 20)),
    "B.II": {21, 22, 23},
}
# Trang có thể thuộc section (kể cả trang chuyển mục) - dùng cho metadata
SECTION_PAGES = {
    "A": {1, 2, 3},
    "B.I": set(range(3, 21)),
    "B.II": {20, 21, 22, 23},
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(BENCH.read_text(encoding="utf-8"))
    pdf_path = ROOT / data["meta"]["source"]
    doc = fitz.open(pdf_path)
    pages = {i + 1: norm(p.get_text()) for i, p in enumerate(doc)}
    assert len(pages) == data["meta"]["total_pages"], "Số trang không khớp meta"

    qs = data["questions"]
    errors, warns = [], []

    ids = [q["id"] for q in qs]
    if len(ids) != len(set(ids)):
        errors.append("ID trùng")

    dev = [q for q in qs if q["split"] == "dev"]
    test = [q for q in qs if q["split"] == "test"]
    flt = [q for q in qs if q.get("filter")]
    flt_test = [q for q in flt if q["split"] == "test"]
    if len(qs) < 20:
        errors.append(f"Chỉ có {len(qs)} câu (<20)")
    if len(dev) < 15 or len(test) < 5:
        errors.append(f"Split dev/test = {len(dev)}/{len(test)} (cần >=15/>=5)")
    if len(flt) < 3 or len(flt_test) < 1:
        errors.append(f"Filter: {len(flt)} câu, {len(flt_test)} thuộc test (cần >=3, >=1)")

    print(f"{'id':4} {'split':5} {'type':13} {'page':>4}  {'ok':3} other_pages_with_quote")
    for q in qs:
        golds = [(q["gold_page"], q["evidence_quote"])] + [
            (a["gold_page"], a["evidence_quote"]) for a in q.get("alt_gold", [])
        ]
        ok_all = True
        others = set()
        for page, quote in golds:
            nq = norm(quote)
            if nq not in pages[page]:
                ok_all = False
                errors.append(f"{q['id']}: evidence KHÔNG có ở trang {page}: {quote[:70]}...")
            others |= {p for p, t in pages.items() if nq in t and p != page}
        # Không rò gold vào query
        if re.search(r"trang\s*\d+|vcb-credit-card", q["question"], re.I):
            errors.append(f"{q['id']}: question chứa tham chiếu trang/source id")
        # Filter hợp lệ
        if q.get("filter"):
            sec = q["filter"].get("section")
            if sec not in PURE_PAGES:
                errors.append(f"{q['id']}: filter section '{sec}' không hợp lệ")
            else:
                for page, _ in golds:
                    if page not in PURE_PAGES[sec]:
                        errors.append(f"{q['id']}: gold p{page} không nằm ở trang thuần của {sec}")
        # Evidence quá ngắn dễ khớp nhiều chỗ
        if len(norm(q["evidence_quote"])) < 30:
            warns.append(f"{q['id']}: evidence ngắn (<30 ký tự)")
        print(f"{q['id']:4} {q['split']:5} {q['type']:13} {q['gold_page']:>4}  "
              f"{'OK' if ok_all else 'XX':3} {sorted(others) or '-'}")

    print(f"\nTổng: {len(qs)} câu | dev={len(dev)} test={len(test)} | filter={len(flt)} (test={len(flt_test)})")
    from collections import Counter
    print("Loại câu:", dict(Counter(q["type"] for q in qs)))
    print("Phân bố trang gold:", sorted(Counter(q["gold_page"] for q in qs).items()))
    for w in warns:
        print("WARN:", w)
    if errors:
        print("\nLỖI:")
        for e in errors:
            print(" -", e)
        return 1
    print("\nTẤT CẢ evidence đã được xác minh nguyên văn ở trang gold. ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
