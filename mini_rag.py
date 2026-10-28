import sys, pathlib, math, re, threading
from collections import Counter
import fitz, chromadb
from sentence_transformers import SentenceTransformer

MODEL = "intfloat/multilingual-e5-base"
SIZE, OVERLAP = 170, 30
_model = None
_col = None
_bm25 = None
_corpus_data = None
_model_lock = threading.Lock()

TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
MADDE_RE = re.compile(r"(?:GEÇİCİ\s+|EK\s+)?MADDE\s*\d+", re.I)

# Korpustaki Tanımlar maddelerinden türetilen resmi kısaltmalar (kural/sayı içermez)
CORPUS_TERMS = [
    (r"\bgano\b", "gano genel ağırlıklı not ortalaması"),
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
            _model = SentenceTransformer(MODEL)
        return _model


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

def extract_page_headings(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    headings = []
    for i, l in enumerate(lines):
        if MADDE_RE.match(l):
            m_tag = MADDE_RE.match(l).group(0)
            prev = (
                lines[i - 1]
                if i > 0
                and len(lines[i - 1].split()) <= 8
                and not MADDE_RE.match(lines[i - 1])
                and not lines[i - 1].isdigit()
                else ""
            )
            headings.append(f"{prev} ({m_tag})" if prev else m_tag)
    return ", ".join(headings[:4])

def build_pdf_chunks(pdf_path: pathlib.Path):
    d = fitz.open(pdf_path)
    stitle = extract_short_title(d, pdf_path.stem)
    last_heading = ""
    page_chunks = []
    step = SIZE - OVERLAP
    for n, page in enumerate(d, 1):
        txt = page.get_text()
        h = extract_page_headings(txt) or last_heading
        if h:
            last_heading = h
        w = txt.split()
        if not w:
            continue
        prefix = f"[{stitle}" + (f" | {h}] " if h else "] ")
        for j in range(0, len(w), step):
            sub = w[j : j + SIZE]
            if not sub:
                continue
            page_chunks.append((n, prefix + " ".join(sub)))
    return page_chunks

class BM25Index:
    def __init__(self, raw_docs, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
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
            term_idf = self.idf[term] * (0.45 if term.startswith("#") else 1.0)
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

def search(q, k=4, use_rewrite=True):
    bm25, corpus_data = get_bm25()
    docs = corpus_data["documents"]
    metas = corpus_data["metadatas"]
    ids = corpus_data["ids"]
    id_to_idx = {id_: i for i, id_ in enumerate(ids)}

    program_level = "genel"
    extra_queries = []
    try:
        from src.query_rewrite import rewrite_query, fallback_rewrite
        rw = rewrite_query(q, use_llm=use_rewrite) if use_rewrite else fallback_rewrite(q)
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

    queries = [q]
    for eq in extra_queries:
        if eq and eq.strip() and eq.strip() not in queries:
            queries.append(eq.strip())

    is_short = len(q.split()) <= 6
    q_embs = encode_texts(["query: " + x for x in queries])
    r = get_col().query(query_embeddings=q_embs, n_results=min(30, len(ids)))

    rrf = Counter()
    best_dist = {}

    for q_idx, q_text in enumerate(queries):
        weight = 1.0 if q_idx == 0 else (0.75 if is_short else 0.35)
        dense_ids = r["ids"][q_idx]
        dists = r["distances"][q_idx]
        for rank, (id_, dist) in enumerate(zip(dense_ids, dists), 1):
            rrf[id_] += weight * (1.0 / (30 + rank))
            if id_ not in best_dist or dist < best_dist[id_]:
                best_dist[id_] = dist

        bm25_q = normalize_terms(q_text)
        bm25_res = bm25.search(bm25_q, top_n=min(30, len(ids)))
        for rank, (_, idx) in enumerate(bm25_res, 1):
            rrf[ids[idx]] += weight * (1.0 / (30 + rank))

    if not is_grad:
        for id_ in list(rrf.keys()):
            if metas[id_to_idx[id_]].get("file") == "lisansustu_egitim.pdf":
                rrf[id_] *= 0.85

    # Sayfa bazında tekilleştirme (aynı sayfadan birden fazla parça gelirse metinlerini birleştir)
    results = []
    seen_pages = {}
    for id_, _ in rrf.most_common(k * 4):
        idx = id_to_idx[id_]
        key = (metas[idx]["file"], metas[idx]["page"])
        if key in seen_pages:
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
            results.append((docs[idx], metas[idx], best_dist.get(id_, 0.20)))

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
