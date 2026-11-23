import sys, pathlib, math, re, threading
from collections import Counter
import pymupdf as fitz
import chromadb
import yaml
from sentence_transformers import SentenceTransformer

CONFIG_PATH = pathlib.Path(__file__).resolve().parent / "config" / "retrieval.yaml"

DEFAULT_CONFIG = {
    "embedding_model": "intfloat/multilingual-e5-base",
    "chunk_size_words": 170,
    "chunk_overlap_words": 30,
    "strip_page_headers": True,
    "article_aware_chunking": True,
    "include_doc_and_article_headings": True,
    "page_deduplication": True,
    "bm25": {
        "k1": 1.5,
        "b": 0.75,
        "turkish_ascii_normalization": True,
        "morphological_stem5_weight": 0.45,
    },
    "rrf": {
        "k": 30,
        "original_query_weight": 1.0,
        "rewrite_query_weight_short": 0.75,
        "rewrite_query_weight_long": 0.35,
        "non_grad_doc_weight": 0.85,
        "grad_doc_boost": 1.25,
    },
    "reranker": {
        "enabled": True,
        "model": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        "candidate_pool": 20,
        "rrf_blend_weight": 0.35,
    },
    "query_rewrite": {
        "enabled": True,
        "model": "gemini-3.5-flash-lite",
        "max_rewritten_queries": 2,
    },
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG)) if "json" in globals() else _deep_copy_cfg(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            for k, v in user_cfg.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def _deep_copy_cfg(d):
    return {k: (_deep_copy_cfg(v) if isinstance(v, dict) else v) for k, v in d.items()}


CFG = load_config()
MODEL = CFG["embedding_model"]
SIZE = int(CFG["chunk_size_words"])
OVERLAP = int(CFG["chunk_overlap_words"])

_model = None
_reranker = None
_reranker_failed = False
_col = None
_bm25 = None
_corpus_data = None
_model_lock = threading.Lock()
_reranker_lock = threading.Lock()

TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
MADDE_RE = re.compile(r"^(?:GEÇİCİ\s+|EK\s+)?MADDE\s*\d+\b", re.I)

# Korpustaki Tanımlar maddelerinden türetilen resmi kısaltmalar (kural/sayı içermez)
CORPUS_TERMS = [
    (r"\bgano\b", "gano genel ağırlıklı not ortalaması genel not ortalaması mezuniyet derecesi"),
    (r"\bdno\b", "dno dönem not ortalaması"),
    (r"\bçap\b|\bcap\b", "çap çift anadal programı"),
    (r"\byandal\b", "yandal yan dal programı"),
    (r"\bakts\b|\bects\b", "akts avrupa kredi transfer sistemi"),
    (r"\bime\b|\b3\+1\b|\b7\+1\b", "ime işletmede mesleki eğitim uygulamalı eğitim"),
    (r"\bmyp\b", "myp mikro yeterlilik programı"),
    (r"\bvize\w*", "vize ara sınav"),
    (r"\bfinal\w*", "final yarıyıl sonu dönem sonu sınavı"),
    (r"\bbüt\b|\bbütünleme\w*", "bütünleme sınavı"),
]


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            try:
                _model = SentenceTransformer(MODEL, local_files_only=True)
            except Exception:
                _model = SentenceTransformer(MODEL)
        return _model


def warmup():
    """Sunucu açılışında embedding/reranker modellerini, BM25 indeksini ve cihaz (MPS/CPU) boru hattını ısıtır."""
    get_model()
    get_bm25()
    encode_texts(["query: test"])
    reranker = get_reranker()
    if reranker is not None:
        with _reranker_lock:
            reranker.predict([("test", "test belgesi")])


def get_reranker():
    global _reranker, _reranker_failed
    rerank_cfg = CFG.get("reranker", {})
    if not rerank_cfg.get("enabled", False) or _reranker_failed:
        return None
    with _reranker_lock:
        if _reranker is None and not _reranker_failed:
            try:
                from sentence_transformers import CrossEncoder
                try:
                    _reranker = CrossEncoder(rerank_cfg["model"], local_files_only=True)
                except Exception:
                    _reranker = CrossEncoder(rerank_cfg["model"])
            except Exception as e:
                print(f"[Uyarı] Reranker yüklenemedi, RRF ile devam ediliyor: {e}", file=sys.stderr)
                _reranker_failed = True
                return None
        return _reranker


def encode_texts(texts: list[str]) -> list[list[float]]:
    m = get_model()
    with _model_lock:
        return m.encode(texts, normalize_embeddings=True).tolist()


def get_col():
    global _col
    if _col is None:
        _col = chromadb.PersistentClient(path="db").get_or_create_collection(
            "docs", metadata={"hnsw:space": "cosine"})
    return _col


def to_ascii(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower().translate(TR_MAP)


def tokenize(text: str) -> list[str]:
    t = to_ascii(text)
    words = re.findall(r"[a-z0-9]+", t)
    tokens = []
    for w in words:
        if len(w) < 2:
            continue
        tokens.append(w)
        if len(w) >= 6:
            stem5 = w[:5]
            if stem5[-1] == "b":
                stem5 = stem5[:-1] + "p"
            elif stem5[-1] == "d":
                stem5 = stem5[:-1] + "t"
            elif stem5[-1] == "g":
                stem5 = stem5[:-1] + "k"
            tokens.append("#" + stem5)
    return tokens


def extract_short_title(pdf_doc, fallback_stem: str) -> str:
    p1_lines = [l.strip() for l in pdf_doc[0].get_text().splitlines() if l.strip()]
    skip_re = re.compile(
        r"^(T\.?C\.?|Resm[iî]\s+Gazete|Say[ıi]\s*:.*|\d+\s+\S+\s+\d{4}\s+\S+|"
        r"YÖNETMELİK|Kayseri\s+Üniversitesinden\s*:|\d+)$",
        re.I,
    )
    stop_re = re.compile(
        r"^(BİRİNCİ\s+BÖLÜM|Amaç|Kapsam|MADDE\s+1\b|Doküman\s+No|YG-\d+|UE-\d+|İlk\s+Yayın)",
        re.I,
    )
    tparts = []
    for l in p1_lines[:18]:
        if stop_re.match(l):
            break
        if skip_re.match(l):
            continue
        if l not in tparts:
            tparts.append(l)
    t = re.sub(r"\s+", " ", " ".join(tparts)).strip()
    half = len(t) // 2
    if len(t) > 20 and t[:half].strip() == t[half:].strip():
        t = t[:half].strip()
    t = re.sub(r"^KAYSERİ\s+ÜNİVERSİTESİ\s+", "", t, flags=re.I)
    return t or fallback_stem


def strip_page_header(text: str) -> list[str]:
    """KAYÜ yönerge PDF'lerindeki tekrarlayan kalite-yönetim üst bilgi tablosunu ve sayfa numarasını temizler."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    if CFG.get("strip_page_headers", True):
        # İlk 10 satır içinde "Doküman No" varsa üst bilgi tablosunun bittiği yere kadar atla
        doc_no_idx = None
        for idx, l in enumerate(lines[:10]):
            if l.lower() == "doküman no":
                doc_no_idx = idx
                break

        if doc_no_idx is not None:
            meta_labels = {"onaylayan", "hazırlayan", "sayfa no", "revizyon no", "revizyon tarihi", "ilk yayın tarihi"}
            end_idx = doc_no_idx + 2
            for idx in range(doc_no_idx, min(len(lines), doc_no_idx + 18)):
                if lines[idx].lower() in meta_labels:
                    end_idx = max(end_idx, idx + 2)
            lines = lines[end_idx:]

        # Başta veya sonda kalan tek başına sayfa numarasını temizle
        while lines and lines[0].isdigit():
            lines.pop(0)
        while lines and lines[-1].isdigit():
            lines.pop()

    return lines


def _is_article_title_line(line: str) -> bool:
    if not line or line.isdigit():
        return False
    if MADDE_RE.match(line):
        return False
    if len(line.split()) > 10:
        return False
    # Fıkra veya bent satırları başlık değildir
    if re.match(r"^(?:\(\d+\)|[a-zçğıöşü]\)|[IVXLCDM]+\.)", line):
        return False
    # Cümle devamı gibi biten satırlar başlık değildir
    if line.endswith((".", ",", ";", ":")):
        return False
    return True


def _split_page_into_article_segments(lines: list[str], initial_heading: str) -> tuple[list[tuple[str, list[str]]], str]:
    """Bir sayfadaki satırları MADDE sınırlarına göre segmentlere ayırır."""
    segments: list[tuple[str, list[str]]] = []
    cur_heading = initial_heading
    cur_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = MADDE_RE.match(line)
        if m:
            m_tag = m.group(0)
            title_line = ""
            # Önceki satır kısa bir madde başlığıysa onu yeni segmente taşı
            if cur_lines and _is_article_title_line(cur_lines[-1]):
                title_line = cur_lines.pop()

            if cur_lines:
                segments.append((cur_heading, cur_lines))

            cur_heading = f"{title_line} ({m_tag})" if title_line else m_tag
            cur_lines = [title_line, line] if title_line else [line]
        else:
            cur_lines.append(line)
        i += 1

    if cur_lines:
        segments.append((cur_heading, cur_lines))

    # Çok kısa (<15 kelime) bölüm başlığı segmentlerini bir sonraki segmente birleştir
    merged: list[tuple[str, list[str]]] = []
    idx = 0
    while idx < len(segments):
        h, seg_lines = segments[idx]
        word_count = len(" ".join(seg_lines).split())
        if word_count < 15 and idx + 1 < len(segments):
            next_h, next_lines = segments[idx + 1]
            segments[idx + 1] = (next_h, seg_lines + next_lines)
        else:
            merged.append((h, seg_lines))
        idx += 1

    last_heading = merged[-1][0] if merged else cur_heading
    return merged, last_heading


def build_pdf_chunks(pdf_path: pathlib.Path):
    d = fitz.open(pdf_path)
    stitle = extract_short_title(d, pdf_path.stem)
    last_heading = ""
    page_chunks = []
    step = max(1, SIZE - OVERLAP)
    use_article_chunking = CFG.get("article_aware_chunking", True)
    include_headings = CFG.get("include_doc_and_article_headings", True)

    for n, page in enumerate(d, 1):
        lines = strip_page_header(page.get_text())
        if not lines:
            continue

        if use_article_chunking:
            segments, last_heading = _split_page_into_article_segments(lines, last_heading)
            for heading, seg_lines in segments:
                w = " ".join(seg_lines).split()
                if not w:
                    continue
                prefix = ""
                if include_headings:
                    prefix = f"[{stitle}" + (f" | {heading}] " if heading else "] ")
                if len(w) <= SIZE:
                    page_chunks.append((n, prefix + " ".join(w)))
                else:
                    for j in range(0, len(w), step):
                        sub = w[j : j + SIZE]
                        if not sub:
                            continue
                        page_chunks.append((n, prefix + " ".join(sub)))
                        if j + SIZE >= len(w):
                            break
        else:
            w = " ".join(lines).split()
            prefix = f"[{stitle}] " if include_headings else ""
            for j in range(0, len(w), step):
                sub = w[j : j + SIZE]
                if sub:
                    page_chunks.append((n, prefix + " ".join(sub)))
    return page_chunks


class BM25Index:
    def __init__(self, raw_docs, k1=None, b=None):
        bm25_cfg = CFG.get("bm25", {})
        self.k1 = k1 if k1 is not None else float(bm25_cfg.get("k1", 1.5))
        self.b = b if b is not None else float(bm25_cfg.get("b", 0.75))
        self.stem_weight = float(bm25_cfg.get("morphological_stem5_weight", 0.45))
        self.corpus = [tokenize(d) for d in raw_docs]
        self.doc_len = [len(c) for c in self.corpus]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 1.0
        self.N = len(self.corpus)
        df = Counter()
        for c in self.corpus:
            for w in set(c):
                df[w] += 1
        self.idf = {
            w: math.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)
            for w, freq in df.items()
        }

    def search(self, query, top_n=30):
        q_tokens = tokenize(query)
        scores = [0.0] * self.N
        for term in q_tokens:
            if term not in self.idf:
                continue
            term_idf = self.idf[term] * (self.stem_weight if term.startswith("#") else 1.0)
            for i, c in enumerate(self.corpus):
                tf = c.count(term)
                if tf > 0:
                    num = tf * (self.k1 + 1)
                    den = tf + self.k1 * (1 - self.b + self.b * (self.doc_len[i] / self.avgdl))
                    scores[i] += term_idf * (num / den)
        ranked = sorted([(scores[i], i) for i in range(self.N) if scores[i] > 0], reverse=True)[:top_n]
        return ranked


def get_bm25():
    global _bm25, _corpus_data
    if _bm25 is None or _corpus_data is None:
        col = get_col()
        _corpus_data = col.get(include=["documents", "metadatas"])
        _bm25 = BM25Index(_corpus_data["documents"])
    return _bm25, _corpus_data


def index():
    global _col, _bm25, _corpus_data
    _col, _bm25, _corpus_data = None, None, None
    client = chromadb.PersistentClient(path="db")
    try:
        client.delete_collection("docs")
    except Exception:
        pass
    col = get_col()
    ids, docs, metas = [], [], []
    for pdf in sorted(pathlib.Path("data").rglob("*.[pP][dD][fF]")):
        if "_taranmis" in pdf.parts:
            continue
        per_page_counter = Counter()
        for n, c in build_pdf_chunks(pdf):
            j = per_page_counter[n]
            per_page_counter[n] += 1
            ids.append(f"{pdf.name}-{n}-{j}")
            docs.append(c)
            metas.append({"file": pdf.name, "page": n})
    emb = get_model().encode(
        ["passage: " + d for d in docs], normalize_embeddings=True, show_progress_bar=True
    ).tolist()
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=emb)
    print(len(docs), "parça indekslendi")


def normalize_terms(q: str) -> str:
    expanded = q
    for pattern, repl in CORPUS_TERMS:
        expanded = re.sub(pattern, repl, expanded, flags=re.IGNORECASE)
    return expanded


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def search(q, k=4, use_rewrite=True, use_reranker=None):
    bm25, corpus_data = get_bm25()
    docs = corpus_data["documents"]
    metas = corpus_data["metadatas"]
    ids = corpus_data["ids"]
    id_to_idx = {id_: i for i, id_ in enumerate(ids)}
    n_res = min(30, len(ids))

    rrf_cfg = CFG.get("rrf", {})
    rrf_k = int(rrf_cfg.get("k", 30))
    w_orig = float(rrf_cfg.get("original_query_weight", 1.0))
    w_short = float(rrf_cfg.get("rewrite_query_weight_short", 0.75))
    w_long = float(rrf_cfg.get("rewrite_query_weight_long", 0.35))
    non_grad_w = float(rrf_cfg.get("non_grad_doc_weight", 0.85))
    grad_boost = float(rrf_cfg.get("grad_doc_boost", 1.25))

    # 1. Orijinal sorgu için hızlı yerel dense + BM25 araması
    orig_emb = encode_texts(["query: " + q])
    orig_r = get_col().query(query_embeddings=orig_emb, n_results=n_res)
    orig_dists = orig_r["distances"][0] if orig_r.get("distances") else []
    top_dist = orig_dists[0] if orig_dists else 1.0
    is_short = len(q.split()) <= 6

    # 2. Akıllı / koşullu sorgu yeniden yazımı
    program_level = "genel"
    extra_queries = []
    try:
        from src.query_rewrite import rewrite_query, fallback_rewrite, get_cached_rewrite

        if use_rewrite:
            cached = get_cached_rewrite(q)
            if cached is not None:
                rw = cached
            elif len(q.split()) <= 8 or top_dist > 0.125:
                rw = rewrite_query(q, use_llm=True)
            else:
                rw = fallback_rewrite(q)
        else:
            rw = fallback_rewrite(q)

        program_level = rw.get("program_level", "genel")
        extra_queries = rw.get("rewritten_queries", [])
    except Exception:
        pass

    grad_check_text = (q + " " + " ".join(extra_queries)).lower()
    grad_terms = (
        "lisansüstü", "lisansustu", "yüksek lisans", "yuksek lisans",
        "doktora", "tez", "tezli", "tezsiz", "enstitü", "enstitu",
        "seminer", "yeterlik", "bilimsel hazırlık"
    )
    is_grad = program_level == "lisansustu" or any(t in grad_check_text for t in grad_terms)

    clean_extras = []
    for eq in extra_queries:
        eq_s = eq.strip() if eq else ""
        if eq_s and eq_s != q and eq_s not in clean_extras:
            clean_extras.append(eq_s)

    rrf = Counter()
    best_dist = {}

    # Orijinal sorgu sonuçlarını RRF'e ekle
    for rank, (id_, dist) in enumerate(zip(orig_r["ids"][0], orig_dists), 1):
        rrf[id_] += w_orig * (1.0 / (rrf_k + rank))
        if id_ not in best_dist or dist < best_dist[id_]:
            best_dist[id_] = dist

    bm25_q0 = normalize_terms(q)
    for rank, (_, idx) in enumerate(bm25.search(bm25_q0, top_n=n_res), 1):
        rrf[ids[idx]] += w_orig * (1.0 / (rrf_k + rank))

    # Yalnızca yeni rewrite sorguları varsa onları encode et ve ekle
    if clean_extras:
        extra_weight = w_short if is_short else w_long
        extra_embs = encode_texts(["query: " + x for x in clean_extras])
        extra_r = get_col().query(query_embeddings=extra_embs, n_results=n_res)
        for q_idx, q_text in enumerate(clean_extras):
            dense_ids = extra_r["ids"][q_idx]
            dists = extra_r["distances"][q_idx]
            for rank, (id_, dist) in enumerate(zip(dense_ids, dists), 1):
                rrf[id_] += extra_weight * (1.0 / (rrf_k + rank))
                if id_ not in best_dist or dist < best_dist[id_]:
                    best_dist[id_] = dist

            bm25_q = normalize_terms(q_text)
            for rank, (_, idx) in enumerate(bm25.search(bm25_q, top_n=n_res), 1):
                rrf[ids[idx]] += extra_weight * (1.0 / (rrf_k + rank))

    for id_ in list(rrf.keys()):
        fname = metas[id_to_idx[id_]].get("file", "")
        if not is_grad and fname == "lisansustu_egitim.pdf":
            rrf[id_] *= non_grad_w
        elif is_grad and fname == "lisansustu_egitim.pdf":
            rrf[id_] *= grad_boost

    rerank_cfg = CFG.get("reranker", {})
    do_rerank = rerank_cfg.get("enabled", True) if use_reranker is None else use_reranker
    reranker = get_reranker() if do_rerank else None

    pool_size = max(k * 4, int(rerank_cfg.get("candidate_pool", 20)))
    candidates = rrf.most_common(pool_size)

    if reranker is not None and candidates:
        rerank_query = q if not is_short or not extra_queries else f"{q} ({extra_queries[0]})"
        pairs = [(rerank_query, docs[id_to_idx[id_]]) for id_, _ in candidates]
        with _reranker_lock:
            ce_raw = reranker.predict(pairs)

        max_rrf = max(s for _, s in candidates) or 1.0
        min_rrf = min(s for _, s in candidates)
        rrf_span = (max_rrf - min_rrf) or 1.0

        ce_vals = [float(x) for x in ce_raw]
        max_ce = max(ce_vals)
        min_ce = min(ce_vals)
        ce_span = (max_ce - min_ce) or 1.0

        blend_w = float(rerank_cfg.get("rrf_blend_weight", 0.35))

        blended = []
        for (id_, rrf_score), ce_score in zip(candidates, ce_vals):
            ce_norm = (ce_score - min_ce) / ce_span
            rrf_norm = (rrf_score - min_rrf) / rrf_span
            fname = metas[id_to_idx[id_]].get("file", "")
            level_mult = 1.0
            if not is_grad and fname == "lisansustu_egitim.pdf":
                level_mult = non_grad_w
            elif is_grad and fname == "lisansustu_egitim.pdf":
                level_mult = grad_boost
            final_score = ((1.0 - blend_w) * ce_norm + blend_w * rrf_norm) * level_mult
            blended.append((id_, final_score))
        blended.sort(key=lambda x: x[1], reverse=True)
        ordered_candidates = blended
    else:
        ordered_candidates = candidates

    # Sayfa bazında tekilleştirme (parent_page_expansion açıksa sayfanın tüm parçaları, kapalıysa eşleşen parçalar birleştirilir)
    use_parent_page = CFG.get("parent_page_expansion", False)
    page_to_indices: dict[tuple[str, int], list[int]] = {}
    if use_parent_page:
        for idx, meta in enumerate(metas):
            page_to_indices.setdefault((meta["file"], meta["page"]), []).append(idx)

    results = []
    seen_pages: dict[tuple[str, int], int] = {}
    for id_, _ in ordered_candidates:
        idx = id_to_idx[id_]
        key = (metas[idx]["file"], metas[idx]["page"])
        if key in seen_pages:
            if not use_parent_page:
                pos = seen_pages[key]
                if docs[idx] not in results[pos][0]:
                    results[pos] = (
                        results[pos][0] + "\n" + docs[idx],
                        results[pos][1],
                        results[pos][2],
                    )
            continue
        if len(results) < k:
            seen_pages[key] = len(results)
            text_out = (
                "\n".join(docs[p_idx] for p_idx in page_to_indices.get(key, [idx]))
                if use_parent_page
                else docs[idx]
            )
            results.append((text_out, metas[idx], best_dist.get(id_, 0.20)))

    return results


def ask(q):
    for d, m, dist in search(q):
        print(f"\n[{m['file']}, s.{m['page']}] mesafe={dist:.2f}\n{d[:350]}...")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım:\n  python mini_rag.py index\n  python mini_rag.py ask \"Soru metni\"")
        sys.exit(1)
    if sys.argv[1] == "index":
        index()
    else:
        q = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
        ask(q)
