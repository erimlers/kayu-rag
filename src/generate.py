import os, queue, sys, time, re, threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mini_rag import search

# .env dosyasını yükle
load_dotenv(override=True)

# Canlı RAG prompt testinde en hızlı ve kararlı model/thinking yapılandırmaları
MODEL_CONFIGS: list[tuple[str, str | None]] = [
    ("gemini-3.1-flash-lite", None),
    ("gemini-3-flash-preview", "minimal"),
    ("gemini-3.5-flash-lite", None),
    ("gemini-flash-lite-latest", None),
    ("gemini-3.6-flash", "minimal"),
]
_CLIENT = None
_CLIENT_LOCK = threading.Lock()
_ANSWER_CACHE: OrderedDict[str, dict] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_MAX_CACHE_SIZE = 256
_MODEL_COOLDOWN: dict[str, float] = {}
_COOLDOWN_LOCK = threading.Lock()
_RECOVERY_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _mark_model_unhealthy(model_name: str, seconds: float = 60.0) -> None:
    with _COOLDOWN_LOCK:
        _MODEL_COOLDOWN[model_name] = time.monotonic() + seconds


def _ordered_healthy_configs() -> list[tuple[str, str | None]]:
    now = time.monotonic()
    with _COOLDOWN_LOCK:
        healthy = [cfg for cfg in MODEL_CONFIGS if _MODEL_COOLDOWN.get(cfg[0], 0.0) <= now]
        cooling = sorted(
            [cfg for cfg in MODEL_CONFIGS if _MODEL_COOLDOWN.get(cfg[0], 0.0) > now],
            key=lambda cfg: _MODEL_COOLDOWN[cfg[0]],
        )
    return healthy + cooling


def _build_gen_config(thinking_level: str | None):
    from google.genai import types
    cfg_kw = {
        "system_instruction": SYSTEM_PROMPT,
        "temperature": 0.1,
        "max_output_tokens": 3072,
    }
    if thinking_level is not None:
        cfg_kw["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    return types.GenerateContentConfig(**cfg_kw)


def _cache_key(question: str, k: int) -> str:
    norm_q = re.sub(r"\s+", " ", question.strip().lower())
    return f"{k}:{norm_q}"


def _get_cached_answer(question: str, k: int) -> dict | None:
    key = _cache_key(question, k)
    with _CACHE_LOCK:
        entry = _ANSWER_CACHE.get(key)
        if entry is not None:
            _ANSWER_CACHE.move_to_end(key)
            return dict(entry)
    return None


def _set_cached_answer(question: str, k: int, payload: dict) -> None:
    key = _cache_key(question, k)
    with _CACHE_LOCK:
        _ANSWER_CACHE[key] = dict(payload)
        _ANSWER_CACHE.move_to_end(key)
        while len(_ANSWER_CACHE) > _MAX_CACHE_SIZE:
            _ANSWER_CACHE.popitem(last=False)

ABSTENTION_PHRASE = "Bu konu hakkında mevcut Kayseri Üniversitesi yönetmelik ve yönergelerinde bir bilgi bulunmamaktadır."

SYSTEM_PROMPT = """Sen Kayseri Üniversitesi (KAYÜ) Resmi Mevzuat ve Yönetmelik Danışmanısın.
Görevin: Öğrencinin sorusunu, YALNIZCA aşağıda verilen 'Yönetmelik ve Yönerge Parçaları'na dayanarak açık, net ve Türkçe olarak yanıtlamaktır.

TEMEL İLKELER:
1. KANIT TABANLILIK (STRICT GROUNDING):
   - Yalnızca verilen bağlamdaki resmi maddeleri ve hükümleri kullan.
   - Kendi genel bilgilerinden, tahminlerden veya diğer üniversitelerin uygulamalarından kesinlikle ekleme yapma.
   - Bağlamda yarıyıl (dönem) bazında verilen sayısal/kredi kuralları varsa (ör. bir yarıyıl 30 AKTS), bunları doğrudan belirterek yıllık (2 yarıyıl = 60 AKTS) karşılığını da aynı maddeye dayandırarak açıklayabilirsin.
   - İlettiğin her bilginin, şartın veya sayının sonuna mutlaka ilgili kaynak etiketini ekle: [belge_adi.pdf, s.X].
   - YALNIZCA yukarıda sana verilen parça başlıklarında (Belge ve Sayfa) geçen dosya adı ve sayfa numaralarına atıf yap; bağlamda olmayan bir sayfa numarası kesinlikle üretme.

2. KISA, EKSİK VEYA KONU BAŞLIĞI ŞEKLİNDEKİ SORGULAR:
   - Öğrenci tam bir soru cümlesi kurmadan yalnızca bir kavram, kısaltma veya yarım cümle yazmışsa (ör. "devamsızlık", "tek ders", "ff alırsam", "muafiyeti geçemezsem", "yatay geçiş"), bunu o konudaki temel mevzuat kurallarını (tanım, başvuru/başarı şartları, oran/süre sınırları ve başarısızlık sonuçları) soran geçerli bir talep olarak kabul et ve bağlamdaki ilgili maddeleri özetle.
   - Bağlamda sorunun bir kısmı yer alıyor ancak spesifik bir alt detay (ör. kesin ücret tutarı, özel bir dergi listesi veya sayısal benzerlik oranı) yer almıyorsa, doğrudan "bilgi bulunmamaktadır" deme; bağlamda yer alan ilgili kuralları kaynaklarıyla açıkla ve hangi spesifik detayın mevcut yönetmelik metinlerinde yer almadığını net biçimde belirt.

3. BELGE VE KAPSAM AYRIMI (YANLIŞ-KONU ENGELLEME):
   - Her parçanın başında [Belge Adı | Madde Başlığı] bilgisi yer alır.
   - Farklı süreçleri düzenleyen yönergeleri (ör. "Önceki Öğrenmelerin/Sertifikaların Tanınması", "Yabancı Dil/Bilgisayar Muafiyet Sınavları", "Ders Muafiyet ve İntibak İşlemleri" veya "Ön Lisans/Lisans" ile "Lisansüstü") birbirine karıştırma. Yanıtında kuralın hangi belge/süreç kapsamında geçerli olduğunu açıkça belirt.
   - Bağlamda hem Kayseri Üniversitesi'nin kendi yönergesi (ör. kurum_ici_yatay_gecis_cap_yandal.pdf) hem de YÖK genel yönetmeliği (yok_yatay_gecis_cap_yandal_yonetmeligi.pdf) birlikte yer alıyorsa, öncelikle KAYÜ'ye özgü kuralları aktar ve YÖK çerçeve hükmünü tamamlayıcı olarak belirt.
   - Kullanıcı özel bir öğrenim düzeyi (lisansüstü/doktora vb.) belirtmedikçe önce ön lisans/lisans temel kurallarını aktar.

4. TAM KAPSAM DIŞI DURUMLAR (ABSTENTION):
   - Yalnızca sağlanan parçaların HİÇBİRİNDE sorulan konuyla ilgili bir hüküm yer almıyorsa (ör. yemekhane, yurt, servis, harç/ücret tutarı, spesifik bir bölümün eğitim dili gibi mevzuat metinlerinde bulunmayan konular), hiçbir kaynak etiketi eklemeden yalnızca şu cümleyi yaz:
     "Bu konu hakkında mevcut Kayseri Üniversitesi yönetmelik ve yönergelerinde bir bilgi bulunmamaktadır."

5. BİÇİM VE TON:
   - Tarafsız, kurumsal ve anlaşılır maddeli bir dil kullan. Gereksiz tekrar yapmadan doğrudan, öz ve maddeli yanıt ver."""


def extract_citations(answer: str) -> list[tuple[str, int | None]]:
    """Yanıttaki tüm [belge.pdf, s.X], [belge.pdf, s. 9, 17], [belge.pdf, s. 4-5] ve çoklu belge atıflarını ayrıştırır."""
    bracket_blocks = re.findall(r"\[([^\]]+\.pdf[^\]]*)\]", answer)
    if not bracket_blocks:
        return []

    citations: list[tuple[str, int | None]] = []
    file_pat = re.compile(r"([a-zA-Z0-9_\-]+\.pdf)")

    for block in bracket_blocks:
        matches = list(file_pat.finditer(block))
        for i, m in enumerate(matches):
            fname = m.group(1)
            seg_start = m.end()
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
            seg = block[seg_start:seg_end]

            pages: list[int] = []
            # Sayfa aralıkları: s. 4-5 veya 4–5
            for r_m in re.finditer(r"(\d+)\s*[-–]\s*(\d+)", seg):
                p1, p2 = int(r_m.group(1)), int(r_m.group(2))
                if p1 <= p2 and (p2 - p1) <= 5:
                    pages.extend(range(p1, p2 + 1))
                else:
                    pages.extend([p1, p2])
            # Tekil sayfa numaraları (aralık dışındakiler de dahil, tekrarları koruyarak ekle)
            seg_no_ranges = re.sub(r"\d+\s*[-–]\s*\d+", "", seg)
            for p_m in re.finditer(r"\b(\d+)\b", seg_no_ranges):
                pages.append(int(p_m.group(1)))

            if pages:
                for p in dict.fromkeys(pages):
                    citations.append((fname, p))
            else:
                citations.append((fname, None))
    return citations


def verify_and_filter_sources(answer: str, sources: list) -> tuple[list, dict]:
    """Yalnızca bağlamda gerçekten bulunan ve yanıtta atıf yapılan kaynakları döner; atıf doğrulama raporu üretir."""
    if ABSTENTION_PHRASE in answer and len(answer.strip()) < len(ABSTENTION_PHRASE) + 120:
        return [], {"total": 0, "verified": 0, "unverified": []}

    citations = extract_citations(answer)
    if not citations:
        return [], {"total": 0, "verified": 0, "unverified": []}

    valid_pairs = {(s.get("file"), int(s.get("page", 0))) for s in sources}
    valid_files = {s.get("file") for s in sources}

    used = []
    seen = set()
    verified_count = 0
    unverified = []

    for c_file, c_page in citations:
        matched = False
        if c_page is not None:
            if (c_file, c_page) in valid_pairs:
                matched = True
        elif c_file in valid_files:
            matched = True

        if matched:
            verified_count += 1
            for s in sources:
                s_file = s.get("file")
                s_page = int(s.get("page", 0))
                if s_file == c_file and (c_page is None or c_page == s_page):
                    key = (s_file, s_page)
                    if key not in seen:
                        seen.add(key)
                        used.append(s)
        else:
            unverified.append(f"{c_file}, s.{c_page}" if c_page is not None else c_file)

    audit = {
        "total": len(citations),
        "verified": verified_count,
        "unverified": list(dict.fromkeys(unverified)),
    }
    return used, audit


def filter_used_sources(answer: str, sources: list) -> list:
    """Geriye dönük uyumluluk için kullanılan kaynakları döner."""
    used, _ = verify_and_filter_sources(answer, sources)
    return used


def clean_abstention_contradiction(answer: str) -> str:
    """Model hem 'bilgi bulunmamaktadır' deyip hem kaynak etiketi eklediyse çelişkiyi temizler."""
    stripped = answer.strip()
    if ABSTENTION_PHRASE in stripped:
        without_citations = re.sub(r"\s*\[[^\]]+\.pdf[^\]]*\]\.?", "", stripped).strip()
        if without_citations == ABSTENTION_PHRASE or len(without_citations) <= len(ABSTENTION_PHRASE) + 25:
            return ABSTENTION_PHRASE
    return stripped


def get_gemini_client():
    global _CLIENT
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or "your_gemini_api_key" in api_key:
        return None
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from google import genai
            _CLIENT = genai.Client(api_key=api_key.strip(), http_options={"timeout": 25000})
        return _CLIENT


def _prepare_context(question: str, results: list, max_chars_per_page: int = 2200) -> tuple[list[dict], str]:
    sources = []
    context_parts = []
    for idx, (doc, meta, dist) in enumerate(results, 1):
        full_doc = doc.strip()
        sources.append({
            "file": meta.get("file", "belge.pdf"),
            "page": meta.get("page", 1),
            "distance": round(float(dist), 3),
            "text": full_doc
        })
        trimmed_doc = full_doc[:max_chars_per_page]
        context_parts.append(
            f"--- [Parça {idx} | Belge: {meta.get('file')} | Sayfa: {meta.get('page')}] ---\n{trimmed_doc}"
        )

    context_text = "\n\n".join(context_parts)
    user_prompt = f"""YÖNETMELİK VE YÖNERGE PARÇALARI:
{context_text}

ÖĞRENCİNİN SORUSU:
{question}

Lütfen yukarıdaki kurallara ve parçalara göre yanıtla:"""
    return sources, user_prompt


def generate_answer(question: str, k: int = 6, use_rewrite: bool = True, precomputed_results=None) -> dict:
    if precomputed_results is None:
        cached = _get_cached_answer(question, k)
        if cached is not None:
            return {
                "question": question,
                **cached,
                "cached": True,
            }

    results = precomputed_results if precomputed_results is not None else search(question, k=k, use_rewrite=use_rewrite)
    sources, user_prompt = _prepare_context(question, results)

    client = get_gemini_client()
    if client is None:
        answer_text = (
            "**Gemini API Anahtarı Tanımlanmadı**\n\n"
            "Cevap üretimi için lütfen `.env` dosyasındaki `GEMINI_API_KEY` alanını doldurun.\n\n"
            "Arama motoru başarıyla çalışmış olup sorunuzla ilgili bulunan yönetmelik maddeleri aşağıda listelenmiştir."
        )
        return {
            "question": question,
            "answer": answer_text,
            "sources": sources,
            "citation_audit": {"total": 0, "verified": 0, "unverified": []},
        }

    for model_name, thinking_level in _ordered_healthy_configs():
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=_build_gen_config(thinking_level),
            )
            if response.text:
                ans = clean_abstention_contradiction(response.text)
                used_sources, citation_audit = verify_and_filter_sources(ans, sources)
                payload = {
                    "answer": ans,
                    "sources": used_sources,
                    "citation_audit": citation_audit,
                    "model": model_name,
                }
                if precomputed_results is None:
                    _set_cached_answer(question, k, payload)
                return {
                    "question": question,
                    **payload,
                    "cached": False,
                }
        except Exception:
            _mark_model_unhealthy(model_name)
            continue

    return {
        "question": question,
        "answer": "Gemini servisinde şu an geçici yoğunluk var. Lütfen birkaç saniye sonra tekrar deneyin.",
        "sources": [],
        "citation_audit": {"total": 0, "verified": 0, "unverified": []},
    }


def _stream_worker(
    client,
    model_name: str,
    thinking_level: str | None,
    user_prompt: str,
    out_q: queue.Queue,
    stop_event: threading.Event,
) -> None:
    try:
        stream = client.models.generate_content_stream(
            model=model_name,
            contents=user_prompt,
            config=_build_gen_config(thinking_level),
        )
        for chunk in stream:
            if stop_event.is_set():
                return
            text = getattr(chunk, "text", None)
            if text:
                out_q.put(("chunk", model_name, text))
        if not stop_event.is_set():
            out_q.put(("end", model_name, None))
    except Exception as e:
        if not stop_event.is_set():
            out_q.put(("err", model_name, e))


def generate_answer_stream(question: str, k: int = 6, use_rewrite: bool = True):
    """Mevzuat arama ve hedged + devre kesicili Gemini akışını SSE olayları olarak üretir."""
    t0 = time.perf_counter()

    cached = _get_cached_answer(question, k)
    if cached is not None:
        yield {
            "type": "done",
            **cached,
            "cached": True,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }
        return

    yield {"type": "status", "message": "Mevzuat taranıyor..."}

    results = search(question, k=k, use_rewrite=use_rewrite)
    sources, user_prompt = _prepare_context(question, results)

    client = get_gemini_client()
    if client is None:
        answer_text = (
            "**Gemini API Anahtarı Tanımlanmadı**\n\n"
            "Cevap üretimi için lütfen `.env` dosyasındaki `GEMINI_API_KEY` alanını doldurun.\n\n"
            "Arama motoru başarıyla çalışmış olup sorunuzla ilgili bulunan yönetmelik maddeleri aşağıda listelenmiştir."
        )
        yield {
            "type": "done",
            "answer": answer_text,
            "sources": sources,
            "citation_audit": {"total": 0, "verified": 0, "unverified": []},
            "model": None,
            "cached": False,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }
        return

    yield {"type": "status", "message": "Yanıt hazırlanıyor..."}

    candidates = _ordered_healthy_configs()[:4]
    out_q: queue.Queue = queue.Queue()
    workers: dict[str, threading.Event] = {}
    next_idx = 0

    def start_next() -> str | None:
        nonlocal next_idx
        if next_idx >= len(candidates):
            return None
        mdl, tl = candidates[next_idx]
        next_idx += 1
        ev = threading.Event()
        workers[mdl] = ev
        threading.Thread(
            target=_stream_worker,
            args=(client, mdl, tl, user_prompt, out_q, ev),
            daemon=True,
        ).start()
        return mdl

    start_next()
    winner: str | None = None
    full_text = ""
    hedge_deadline = time.perf_counter() + 2.2

    while workers:
        if winner is None and next_idx == 1 and len(candidates) > 1:
            wait_s = max(0.05, min(0.5, hedge_deadline - time.perf_counter()))
        elif winner is None:
            wait_s = 7.0
        else:
            wait_s = 14.0

        try:
            kind, mdl, payload = out_q.get(timeout=wait_s)
        except queue.Empty:
            if winner is None and next_idx == 1 and len(candidates) > 1 and time.perf_counter() >= hedge_deadline:
                start_next()
                continue
            if winner is None:
                for m_active, ev in list(workers.items()):
                    ev.set()
                    _mark_model_unhealthy(m_active)
                workers.clear()
                if next_idx < len(candidates):
                    start_next()
                    hedge_deadline = time.perf_counter() + 2.2
                    continue
                break
            workers.pop(winner, None)
            _mark_model_unhealthy(winner)
            break

        if kind == "chunk":
            if winner is None:
                winner = mdl
                for other_m, other_ev in list(workers.items()):
                    if other_m != winner:
                        other_ev.set()
                        workers.pop(other_m, None)
            if mdl == winner:
                full_text += payload
                yield {"type": "chunk", "text": payload}
        elif kind == "end":
            workers.pop(mdl, None)
            if mdl == winner and full_text.strip():
                ans = clean_abstention_contradiction(full_text)
                used_sources, citation_audit = verify_and_filter_sources(ans, sources)
                res_payload = {
                    "answer": ans,
                    "sources": used_sources,
                    "citation_audit": citation_audit,
                    "model": winner,
                }
                _set_cached_answer(question, k, res_payload)
                yield {
                    "type": "done",
                    **res_payload,
                    "cached": False,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
                return
            if winner is None and not workers and next_idx < len(candidates):
                start_next()
                hedge_deadline = time.perf_counter() + 2.2
        elif kind == "err":
            workers.pop(mdl, None)
            _mark_model_unhealthy(mdl)
            if winner is None:
                if not workers and next_idx < len(candidates):
                    start_next()
                    hedge_deadline = time.perf_counter() + 2.2
            elif mdl == winner:
                break

    for ev in workers.values():
        ev.set()

    # Akış ortası kopma koruması (Mid-Stream Recovery)
    if winner is not None:
        remaining = [cfg for cfg in _ordered_healthy_configs() if cfg[0] != winner][:2]
        for rec_model, rec_tl in remaining:
            try:
                def _recover(m=rec_model, tl=rec_tl):
                    return client.models.generate_content(
                        model=m,
                        contents=user_prompt,
                        config=_build_gen_config(tl),
                    )

                resp = _RECOVERY_EXECUTOR.submit(_recover).result(timeout=12.0)
                if resp.text and resp.text.strip():
                    yield {"type": "reset", "message": "Yanıt tamamlanıyor..."}
                    ans = clean_abstention_contradiction(resp.text)
                    used_sources, citation_audit = verify_and_filter_sources(ans, sources)
                    res_payload = {
                        "answer": ans,
                        "sources": used_sources,
                        "citation_audit": citation_audit,
                        "model": rec_model,
                    }
                    _set_cached_answer(question, k, res_payload)
                    yield {
                        "type": "done",
                        **res_payload,
                        "cached": False,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    }
                    return
            except Exception:
                _mark_model_unhealthy(rec_model)
                continue

    yield {
        "type": "error",
        "message": "Gemini servisinde şu an geçici yoğunluk var. Lütfen birkaç saniye sonra tekrar deneyin.",
    }


if __name__ == "__main__":
    test_q = sys.argv[1] if len(sys.argv) > 1 else "mezun olmam için kaç gano lazım"
    print(f"Soru: {test_q}\n")
    res = generate_answer(test_q)
    print("CEVAP:\n", res["answer"])
    print("\nKAYNAKLAR (Yalnızca Cevapta Kullanılanlar):")
    for s in res["sources"]:
        print(f"- [{s['file']}, s.{s['page']}] mesafe={s['distance']}")
    if res.get("citation_audit", {}).get("unverified"):
        print("\nUYARI - Doğrulanamayan Atıflar:", res["citation_audit"]["unverified"])
