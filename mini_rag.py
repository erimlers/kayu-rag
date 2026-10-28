import sys, pathlib, math, re
from collections import Counter
import fitz, chromadb
from sentence_transformers import SentenceTransformer

MODEL = "intfloat/multilingual-e5-base"
SIZE, OVERLAP = 200, 30
_model = None
_bm25 = None
_corpus_data = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL)
    return _model

def chunk(text):
    w = text.split()
    return [" ".join(w[i:i + SIZE]) for i in range(0, len(w), SIZE - OVERLAP) if w[i:i + SIZE]]

def get_col():
    return chromadb.PersistentClient(path="db").get_or_create_collection(
        "docs", metadata={"hnsw:space": "cosine"})

def tokenize(text):
    text = text.lower().replace("i̇", "i").replace("ı", "i")
    return re.findall(r"\w+", text)

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
        self.idf = {}
        for w, freq in df.items():
            self.idf[w] = math.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)

    def search(self, query, top_n=20):
        q_tokens = tokenize(query)
        scores = [0.0] * self.N
        for term in q_tokens:
            if term not in self.idf:
                continue
            term_idf = self.idf[term]
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
    global _bm25, _corpus_data
    _bm25, _corpus_data = None, None
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
        for n, page in enumerate(fitz.open(pdf), 1):
            for j, c in enumerate(chunk(page.get_text())):
                ids.append(f"{pdf.name}-{n}-{j}"); docs.append(c)
                metas.append({"file": pdf.name, "page": n})
    emb = get_model().encode(["passage: " + d for d in docs], normalize_embeddings=True,
                             show_progress_bar=True).tolist()
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=emb)
    print(len(docs), "parça indekslendi")

def expand_query(q: str) -> str:
    """Öğrenci kısaltmalarını ve terimlerini mevzuat diliyle zenginleştirir."""
    expansions = [
        (r"\bgano\b", "gano genel ağırlıklı not ortalaması mezuniyet derecesi"),
        (r"\bdno\b", "dno dönem not ortalaması"),
        (r"\bçap\b", "çap çift anadal"),
        (r"\byandal\b", "yandal yan dal"),
        (r"\bakts\b", "akts kredi"),
        (r"\balttan\b", "alttan bütün derslerini alıp başarılı olmak"),
        (r"\bff\b", "ff başarısız ders bütün dersleri başarıyla tamamlamak"),
        (r"\bvize\b", "vize ara sınav"),
        (r"\bfinal\b", "final dönem sonu yarıyıl sonu sınavı"),
        (r"\brapor\b", "rapor sağlık raporu mazeret belgesi"),
        (r"\b3\+1\b", "3+1 mesleki eğitim"),
        (r"\b7\+1\b", "7+1 mesleki eğitim"),
    ]
    expanded = q
    for pattern, repl in expansions:
        expanded = re.sub(pattern, repl, expanded, flags=re.IGNORECASE)
    return expanded

def search(q, k=4):
    bm25, corpus_data = get_bm25()
    docs = corpus_data["documents"]
    metas = corpus_data["metadatas"]
    ids = corpus_data["ids"]
    id_to_idx = {id_: i for i, id_ in enumerate(ids)}

    search_q = expand_query(q)

    # 1. Vektör (Dense) Arama
    qe = get_model().encode(["query: " + search_q], normalize_embeddings=True).tolist()
    r = get_col().query(query_embeddings=qe, n_results=min(20, len(ids)))
    dense_ids = r["ids"][0]
    dense_dists = {id_: r["distances"][0][idx] for idx, id_ in enumerate(dense_ids)}

    # 2. BM25 (Kelime / Sparse) Arama
    bm25_res = bm25.search(search_q, top_n=min(20, len(ids)))

    # 3. Reciprocal Rank Fusion (RRF, k=60)
    rrf = Counter()
    for rank, id_ in enumerate(dense_ids, 1):
        rrf[id_] += 1.0 / (60 + rank)
    for rank, (score, idx) in enumerate(bm25_res, 1):
        rrf[ids[idx]] += 1.0 / (60 + rank)

    top_ids = [id_ for id_, _ in rrf.most_common(k)]
    return [(docs[id_to_idx[id_]], metas[id_to_idx[id_]], dense_dists.get(id_, 0.20)) for id_ in top_ids]

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
