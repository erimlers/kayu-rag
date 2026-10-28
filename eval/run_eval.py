import json, sys
from datetime import datetime
from pathlib import Path

PAGE_TOL = 0  # 0 = tam sayfa eşleşmesi; 1 = ±1 sayfa tolerans

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mini_rag import search

def evaluate(questions_path="eval/questions.json", k=4):
    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    hit1, hit3 = 0, 0
    rr_total = 0.0
    ans_count = 0
    ans_distances = []
    unans_distances = []

    print(f"\n{'='*75}")
    print(f"{'RAG RETRIEVAL DEĞERLENDİRME RAPORU':^75}")
    print(f"{'='*75}\n")

    for q in questions:
        qid = q["id"]
        soru = q["soru"]
        cevapsiz = q["cevapsiz"]
        beklenen_dosya = q.get("beklenen_dosya")
        beklenen_sayfa = q.get("beklenen_sayfa")
        # Aynı cevap birden fazla belgede/sayfada geçiyorsa hepsi geçerli sayılır
        kabul = [(beklenen_dosya, beklenen_sayfa)] + [
            (a["dosya"], a["sayfa"]) for a in q.get("ek_kabul", [])]

        results = search(soru, k=k)
        top1_dist = results[0][2] if results else 1.0

        if cevapsiz:
            unans_distances.append(top1_dist)
            print(f"[SORU {qid:02d} - CEVAPSIZ] {soru[:55]:55s} Top-1 Mesafe: {top1_dist:.3f}")
        else:
            ans_count += 1
            ans_distances.append(top1_dist)

            # Doğru belgenin ve sayfanın hangi sırada olduğunu bul
            rank = None
            for idx, (doc, meta, dist) in enumerate(results, 1):
                # Dosya adı eşleşiyor mu ve sayfa numarası tutuyor mu?
                # (Bazen madde bir önceki/sonraki sayfaya taşmış olabilir, tolerans +-1 sayfa kabul edilebilir veya tam eşleşme)
                eslesen = any(meta["file"] == f and p is not None and abs(meta["page"] - p) <= PAGE_TOL
                              for f, p in kabul)
                if eslesen:
                    rank = idx
                    break

            if rank == 1:
                hit1 += 1
                hit3 += 1
                rr_total += 1.0
                durum = "✓ Hit@1"
            elif rank and rank <= 3:
                hit3 += 1
                rr_total += (1.0 / rank)
                durum = f"✓ Hit@{rank}"
            else:
                durum = "✗ Kaçırdı" if rank is None else f"- Hit@{rank}"
                if rank:
                    rr_total += (1.0 / rank)

            print(f"[SORU {qid:02d}] {soru[:48]:48s} | {durum:10s} | Top-1: {top1_dist:.3f} ({results[0][1]['file'][:25]})")

    hit1_rate = (hit1 / ans_count) * 100 if ans_count else 0
    hit3_rate = (hit3 / ans_count) * 100 if ans_count else 0
    mrr = (rr_total / ans_count) if ans_count else 0
    avg_ans_dist = sum(ans_distances) / len(ans_distances) if ans_distances else 0
    avg_unans_dist = sum(unans_distances) / len(unans_distances) if unans_distances else 0

    print(f"\n{'-'*75}")
    print(f"ÖZET METRİKLER (Toplam {len(questions)} Soru, {ans_count} Cevaplı, {len(unans_distances)} Cevapsız):")
    print(f"  • Hit@1              : %{hit1_rate:.1f} ({hit1}/{ans_count})")
    print(f"  • Hit@3              : %{hit3_rate:.1f} ({hit3}/{ans_count})")
    print(f"  • MRR (Mean RR)      : {mrr:.3f}")
    print(f"  • Cevaplı Ort. Mesafe: {avg_ans_dist:.3f}")
    print(f"  • Cevapsız Ort. Mesafe: {avg_unans_dist:.3f}")
    print(f"{'='*75}\n")

    etiket = sys.argv[1] if len(sys.argv) > 1 else "etiketsiz"
    with open("eval/sonuclar.md", "a", encoding="utf-8") as f:
        f.write(f"| {datetime.now():%Y-%m-%d %H:%M} | {etiket} | tol={PAGE_TOL} | "
                f"{ans_count}+{len(unans_distances)} | {hit1_rate:.1f} | {hit3_rate:.1f} | "
                f"{mrr:.3f} | {avg_ans_dist:.3f} | {avg_unans_dist:.3f} |\n")

if __name__ == "__main__":
    evaluate()
