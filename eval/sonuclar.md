# Deney ve Değerlendirme Sonuçları

Bu dosya `python3 eval/run_eval.py` çalıştırmalarının kayıtlarını ve mimari faz karşılaştırmalarını içerir.

## 1. Overfit Sonrası Değerlendirme Mimarisi (Faz 0–6)

Eski 50 soruluk set (`eval/dev.json`) yalnızca geliştirme/analiz için ayrılmış; sistem çıktısına ve koda bakılmadan doğrudan 19 PDF yönetmelik/yönerge metninden üç bağımsız veri seti üretilmiştir:
- **Kilitli Test Seti (`eval/test_locked.json`, n=80):** Doğal tam cümleli öğrenci soruları (SHA-256 kilidi: `b194200b...`). Hiperparametre, parçalama ve prompt geliştirme sürecinde hiç açılmamıştır.
- **Kısa / Gürültülü Stres Seti (`eval/noisy.json`, n=60):** Tek kelime, yarım cümle (fragment), yazım hatalı ve konuşma dili/argo sorular.
- **Cevapsız Set (`eval/unanswerable.json`, n=30):** 15 tamamen kapsam dışı + 15 mevzuata yakın görünüp belgelerde cevabı olmayan soru.

### Faz 6 Güncellemesi (Doğruluk Artırma Paketi)
- **PDF Üst Bilgi Temizliği & Madde-Duyarlı Parçalama:** Yönerge sayfalarındaki tekrarlayan kalite-yönetim tabloları temizlendi; sabit kelime penceresi yerine `MADDE` sınırlarına duyarlı parçalama (652 temiz parça) getirildi.
- **2. Aşama Cross-Encoder Reranker:** RRF (k=30) aday havuzu `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` ile yeniden sıralandı; `is_grad=True` için lisansüstü belge ağırlığı (`1.25`) ve `config/retrieval.yaml` entegrasyonu eklendi.
- **Atıf Doğrulama ve Deterministik Model:** Çoklu sayfa (`s. 9, 17`) ve aralık (`s. 4-5`) atıf filtreleme hatası düzeltildi; bağlamda olmayan atıfları yakalayan `citation_audit` eklendi; round-robin kaldırılarak sabit birincil model + kota hatasında fallback yapısına geçildi.

### Özet Karşılaştırma Tablosu (Retrieval + Uçtan Uca LLM-Hakem)

| Veri Seti | Sistem Versiyonu | Soru (n) | Hit@1 (%95 GA) | Hit@3 (%95 GA) | Hit@5 | MRR (%95 GA) | Uçtan Uca Doğru+Kısmen (%95 GA) | Geçerli Atıf | Gereksiz Abstention |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `eval/dev.json` | Eski Sistem (Overfit Regex) | 40 | %70.0 | %100.0 | %100.0 | 0.846 | - | - | - |
| `eval/dev.json` | Saf Başlangıç (Regex Kaldırıldı) | 40 | %67.5 | %90.0 | %95.0 | 0.779 | - | - | - |
| `eval/dev.json` | Faz 1–3 (Hibrit + Rewrite) | 40 | %65.0 (%50.0–%80.0) | %95.0 (%87.5–%100.0) | %97.5 | 0.769 (0.665–0.871) | - | - | - |
| `eval/dev.json` | **Faz 6 (Madde Chunk + Reranker)** | 40 | **%62.5** (%47.5–%77.5) | **%92.5** (%82.5–%100.0) | **%97.5** | **0.760** (0.662–0.858) | **%83.3** | **%97.2** | **%2.8** |
| `eval/noisy.json` | Eski Sistem (Baseline) | 60 | %46.7 | %71.7 | %80.0 | 0.603 | - | - | ~%50 |
| `eval/noisy.json` | Faz 1 (Rewrite Kapalı) | 60 | %60.0 | %78.3 | %88.3 | 0.700 | - | - | - |
| `eval/noisy.json` | Faz 1–3 (Hibrit + Rewrite) | 60 | %61.7 (%50.0–%73.3) | %88.3 (%80.0–%95.0) | %95.0 | 0.740 (0.657–0.825) | %96.7 (%91.7–%100.0) | - | %0.0 (0/60) |
| `eval/noisy.json` | **Faz 6 (Madde Chunk + Reranker)** | 60 | **%76.7** (%65.0–%86.7) | **%90.0** (%81.7–%96.7) | **%93.3** | **0.832** (0.747–0.912) | **%94.6** | **%94.6** | **%0.0** |
| `eval/test_locked.json` | Faz 1–3 (İlk Kilitli Test) | 80 | %80.0 (%71.2–%88.8) | %95.0 (%90.0–%98.8) | %98.8 | 0.875 (0.819–0.930) | %88.8 (%81.2–%95.0) | - | %0.0 (0/80) |
| `eval/test_locked.json` | **Faz 6 (Madde Chunk + Reranker)** | 80 | **%96.2** (%92.5–%100.0) | **%100.0** (%100.0–%100.0) | **%100.0** | **0.981** (0.963–1.000) | **%100.0** (Tam Doğru %97.3) | **%98.7** | **%0.0** |

### Cevapsız Sorular (`eval/unanswerable.json`, n=30) Abstention Performansı
| Sistem Versiyonu | Doğru Abstention (`unanswerable.json`, n=30) | %95 Bootstrap GA | `dev.json` Cevapsız (n=10) |
| :--- | :---: | :---: | :---: |
| Faz 1–3 (Hibrit + Rewrite) | %86.7 (26/30) | %73.3 – %96.7 | - |
| **Faz 6 (Madde Chunk + Reranker + Prompt)** | **%93.3 (28/30)** | **%83.3 – %100.0** | **%100.0 (10/10)** |

---

## 2. Ham Çalıştırma Kayıtları (`run_eval.py` Logu)

| Tarih | Deney | Sayfa toleransı | Soru (cevaplı+cevapsız) | Hit@1 % | Hit@3 % | MRR | Cevaplı ort. mesafe | Cevapsız ort. mesafe |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 2026-10-28 01:49 | baseline-tam-sayfa | tol=0 | 16+4 | 62.5 | 93.8 | 0.776 | 0.125 | 0.171 |
| 2026-10-28 01:58 | baseline-v2-32soru | tol=0 | 26+6 | 50.0 | 80.8 | 0.647 | 0.131 | 0.162 |
| 2026-10-28 02:00 | deney1-parca-basligi | tol=0 | 26+6 | 50.0 | 80.8 | 0.631 | 0.132 | 0.163 |
| 2026-10-28 03:51 | 50_soru_dogal_insan_dili | tol=0 | 40+10 | 35.0 | 47.5 | 0.429 | 0.134 | 0.186 |
| 2026-10-28 03:52 | 50_soru_dogal_insan_dili | tol=0 | 40+10 | 52.5 | 75.0 | 0.654 | 0.134 | 0.186 |
| 2026-10-28 03:53 | 50_soru_dogal_insan_dili_v2 | tol=0 | 40+10 | 50.0 | 72.5 | 0.635 | 0.132 | 0.186 |
| 2026-10-28 03:58 | genel_ir_optimizasyonu_rrf30 | tol=0 | 40+10 | 52.5 | 80.0 | 0.662 | 0.135 | 0.189 |
| 2026-10-28 13:52 | hibrit_genel_optimizasyon (eski overfit) | tol=0 | 40+10 | 70.0 | 100.0 | 0.846 | 0.135 | 0.189 |
| 2026-10-29 00:10 | final_retrieval_dev (dev, 905f366) | tol=0 | 40+10 | 65.0 | 95.0 | 0.769 | 0.121 | - |
| 2026-10-29 00:34 | final_e2e_noisy (noisy, 905f366) | tol=0 | 60+0 | 61.7 | 88.3 | 0.740 | 0.146 | - |
| 2026-10-29 00:41 | final_e2e_test_locked (test_locked, 905f366) | tol=0 | 80+0 | 80.0 | 95.0 | 0.875 | 0.126 | - |
| 2026-11-21 21:53 | faz6_madde_reranker (dev) | tol=0 | 40+10 | 62.5 | 92.5 | 0.760 | - | - |
| 2026-11-21 21:57 | faz6_madde_reranker (noisy) | tol=0 | 60+0 | 76.7 | 90.0 | 0.832 | - | - |
| 2026-11-21 22:11 | faz6_madde_reranker (test_locked) | tol=0 | 80+0 | 96.2 | 100.0 | 0.981 | - | - |
