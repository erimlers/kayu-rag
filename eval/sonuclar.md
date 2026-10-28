# Deney ve Değerlendirme Sonuçları

Bu dosya `python3 eval/run_eval.py` çalıştırmalarının kayıtlarını içerir.

## 1. Overfit Sonrası Yeni Değerlendirme Mimarisi (Faz 0–5)

Eski 50 soruluk set (`eval/dev.json`) yalnızca geliştirme/analiz için ayrılmış; sistem çıktısına ve koda bakılmadan doğrudan 19 PDF yönetmelik/yönerge metninden üç yeni bağımsız veri seti üretilmiştir:
- **Kilitli Test Seti (`eval/test_locked.json`, n=80):** Doğal tam cümleli öğrenci soruları (SHA-256 kilidi: `b194200b...`). Hiperparametre ve prompt geliştirme sürecinde hiç kullanılmamıştır.
- **Kısa / Gürültülü Stres Seti (`eval/noisy.json`, n=60):** Tek kelime, yarım cümle (fragment), yazım hatalı ve konuşma dili/argo sorular.
- **Cevapsız Set (`eval/unanswerable.json`, n=30):** 15 tamamen kapsam dışı + 15 mevzuata yakın görünüp belgelerde cevabı olmayan soru.

### Özet Karşılaştırma Tablosu (Retrieval + Uçtan Uca LLM-Hakem)

| Veri Seti | Sistem Versiyonu | Soru (n) | Hit@1 (%95 GA) | Hit@3 (%95 GA) | Hit@5 | MRR (%95 GA) | Uçtan Uca Doğru+Kısmen (%95 GA) | Gereksiz Abstention |
|---|---|---:|---|---|---|---|---|---|
| `eval/dev.json` | Eski Sistem (Overfit Regex) | 40 | %70.0 | %100.0 | %100.0 | 0.846 | Ölçülmedi | Ölçülmedi |
| `eval/dev.json` | Saf Başlangıç (Regex Kaldırıldı) | 40 | %67.5 | %90.0 | %95.0 | 0.779 | - | - |
| `eval/dev.json` | **Yeni Sistem (Faz 1–3)** | 40 | **%65.0** (%50.0–%80.0) | **%95.0** (%87.5–%100.0) | **%97.5** | **0.769** (0.665–0.871) | - | - |
| `eval/noisy.json` | Eski Sistem (Baseline) | 60 | %46.7 | %71.7 | %80.0 | 0.603 | - | Yüksek (~%50 fragmentlarda) |
| `eval/noisy.json` | Yeni Sistem - Sadece Faz 1 (Rewrite Kapalı) | 60 | %60.0 | %78.3 | %88.3 | 0.700 | - | - |
| `eval/noisy.json` | **Yeni Sistem (Faz 1–3 Tam)** | 60 | **%61.7** (%50.0–%73.3) | **%88.3** (%80.0–%95.0) | **%95.0** | **0.740** (0.657–0.825) | **%96.7** (%91.7–%100.0) | **%0.0** (0/60) |
| `eval/test_locked.json` | **Yeni Sistem (Tek Seferlik Final Test)** | 80 | **%80.0** (%71.2–%88.8) | **%95.0** (%90.0–%98.8) | **%98.8** | **0.875** (0.819–0.930) | **%88.8** (%81.2–%95.0) | **%0.0** (0/80) |

### Cevapsız Sorular (`eval/unanswerable.json`, n=30) Abstention Performansı
- **Doğru Abstention Oranı:** **%86.7 (26/30)** `[%95 GA: %73.3 - %96.7]`
- Tamamen kapsam dışı sorularda (yemekhane, yurt, servis, otopark, bölüm eğitim dili vb.) doğru biçimde çekimser kalmakta ve kaynak uydurmamaktadır.

---

## 2. Ham Çalıştırma Kayıtları (`run_eval.py` Logu)

| Tarih | Deney | Sayfa toleransı | Soru (cevaplı+cevapsız) | Hit@1 % | Hit@3 % | MRR | Cevaplı ort. mesafe | Cevapsız ort. mesafe |
|---|---|---|---|---|---|---|---|---|
| 2026-10-28 01:49 | baseline-tam-sayfa | tol=0 | 16+4 | 62.5 | 93.8 | 0.776 | 0.125 | 0.171 |
| 2026-10-28 01:58 | baseline-v2-32soru | tol=0 | 26+6 | 50.0 | 80.8 | 0.647 | 0.131 | 0.162 |
| 2026-10-28 02:00 | deney1-parca-basligi | tol=0 | 26+6 | 50.0 | 80.8 | 0.631 | 0.132 | 0.163 |
| 2026-10-28 03:51 | 50_soru_dogal_insan_dili | tol=0 | 40+10 | 35.0 | 47.5 | 0.429 | 0.134 | 0.186 |
| 2026-10-28 03:52 | 50_soru_dogal_insan_dili | tol=0 | 52.5 | 75.0 | 0.654 | 0.134 | 0.186 |
| 2026-10-28 03:53 | 50_soru_dogal_insan_dili_v2 | tol=0 | 40+10 | 50.0 | 72.5 | 0.635 | 0.132 | 0.186 |
| 2026-10-28 03:58 | genel_ir_optimizasyonu_rrf30 | tol=0 | 40+10 | 52.5 | 80.0 | 0.662 | 0.135 | 0.189 |
| 2026-10-28 13:52 | hibrit_genel_optimizasyon (eski overfit) | tol=0 | 40+10 | 70.0 | 100.0 | 0.846 | 0.135 | 0.189 |
| 2026-10-29 00:10 | final_retrieval_dev (dev, 905f366) | tol=0 | 40+10 | 65.0 | 95.0 | 0.769 | 0.121 | - |
| 2026-10-29 00:34 | final_e2e_noisy (noisy, 905f366) | tol=0 | 60+0 | 61.7 | 88.3 | 0.740 | 0.146 | - |
| 2026-10-29 00:41 | final_e2e_test_locked (test_locked, 905f366) | tol=0 | 80+0 | 80.0 | 95.0 | 0.875 | 0.126 | - |
