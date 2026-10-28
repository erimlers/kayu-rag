import csv, pathlib, re, fitz

AYLAR = {"ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
         "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12}

def norm(t):
    t = t.replace("İ", "i").replace("I", "ı").lower()
    return t.translate(str.maketrans("âîûçğıöşü", "aiucgiosu"))

NUM = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
TXT = re.compile(r"(\d{1,2})\s+(" + "|".join(AYLAR) + r")\s+(\d{4})")

def dates_in(text):
    found = []
    for m in NUM.finditer(text):
        d, mo, y = map(int, m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31 and 1990 <= y <= 2026:
            found.append((m.start(), f"{y}-{mo:02d}-{d:02d}"))
    for m in TXT.finditer(text):
        d, y = int(m.group(1)), int(m.group(3))
        if 1 <= d <= 31 and 1990 <= y <= 2026:
            found.append((m.start(), f"{y}-{AYLAR[m.group(2)]:02d}-{d:02d}"))
    return sorted(found)

def find_date(doc):
    first_pages = norm(" ".join(doc[i].get_text() for i in range(min(2, len(doc)))))
    all_dates = dates_in(first_pages)
    for m in re.finditer(r"resmi gazete", first_pages):
        near = [d for pos, d in all_dates if m.start() <= pos <= m.start() + 150]
        if near:
            return near[0], "resmi_gazete"
    if all_dates:
        return all_dates[0][1], "ilk_tarih"
    # İlk 2 sayfada tarih yoksa son sayfaları kontrol et (Senato kabul / Resmi Gazete tablosu)
    last_pages = norm(" ".join(doc[i].get_text() for i in range(max(0, len(doc) - 2), len(doc))))
    end_dates = dates_in(last_pages)
    if end_dates:
        return end_dates[-1][1], "son_sayfa_senato"
    return "2025", "varsayilan"

rows = []
for pdf in sorted(pathlib.Path("data").rglob("*.[pP][dD][fF]")):
    doc = fitz.open(pdf)
    chars = sum(len(p.get_text()) for p in doc)
    tarih, kaynak = find_date(doc) if chars > 500 else ("", "metin_yok")
    rows.append({
        "dosya": pdf.name, "tur": pdf.parent.name, "sayfa": len(doc),
        "karakter": chars, "metin_var": "evet" if chars > 500 else "HAYIR",
        "yururluk_tarihi": tarih, "tarih_kaynagi": kaynak,
        "kaynak_url": "", "indirme_tarihi": "2026-10-28", "not": "",
    })

with open("data/envanter.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)

print(len(rows), "dosya yazıldı\n")
for r in rows:
    print(f"{r['dosya'][:45]:45s} {r['yururluk_tarihi']:11s} ({r['tarih_kaynagi']})")