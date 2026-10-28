# Deney sonuçları

Her satır `python3 eval/run_eval.py "etiket"` çalıştırmasının özetidir. Küçük değerlendirme setidir, sonuçlar yalnızca bu sette ölçülenleri gösterir.

| Tarih | Deney | Sayfa toleransı | Soru (cevaplı+cevapsız) | Hit@1 % | Hit@3 % | MRR | Cevaplı ort. mesafe | Cevapsız ort. mesafe |
|---|---|---|---|---|---|---|---|---|
| 2026-10-28 01:49 | baseline-tam-sayfa | tol=0 | 16+4 | 62.5 | 93.8 | 0.776 | 0.125 | 0.171 |
| 2026-10-28 01:58 | baseline-v2-32soru | tol=0 | 26+6 | 50.0 | 80.8 | 0.647 | 0.131 | 0.162 |
| 2026-10-28 02:00 | deney1-parca-basligi | tol=0 | 26+6 | 50.0 | 80.8 | 0.631 | 0.132 | 0.163 |
| 2026-10-28 03:51 | 50_soru_dogal_insan_dili | tol=0 | 40+10 | 35.0 | 47.5 | 0.429 | 0.134 | 0.186 |
| 2026-10-28 03:52 | 50_soru_dogal_insan_dili | tol=0 | 40+10 | 52.5 | 75.0 | 0.654 | 0.134 | 0.186 |
| 2026-10-28 03:53 | 50_soru_dogal_insan_dili_v2 | tol=0 | 40+10 | 50.0 | 72.5 | 0.635 | 0.132 | 0.186 |
| 2026-10-28 03:58 | genel_ir_optimizasyonu_rrf30 | tol=0 | 40+10 | 52.5 | 80.0 | 0.662 | 0.135 | 0.189 |
