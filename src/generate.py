import os, sys, time, re
from pathlib import Path
from dotenv import load_dotenv

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mini_rag import search

# .env dosyasını yükle
load_dotenv(override=True)

CANDIDATE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash"
]

SYSTEM_PROMPT = """Sen Kayseri Üniversitesi (KAYÜ) Resmi Mevzuat ve Yönetmelik Danışmanısın.
Görevin: Öğrencinin sorusunu, YALNIZCA aşağıda verilen 'Yönetmelik ve Yönerge Parçaları'na dayanarak açık, net ve Türkçe olarak yanıtlamaktır.

TEMEL İLKELER:
1. KANIT TABANLILIK (STRICT GROUNDING):
   - Yalnızca verilen bağlamdaki resmi maddeleri ve hükümleri kullan.
   - Kendi genel bilgilerinden, tahminlerden veya diğer üniversitelerin uygulamalarından kesinlikle ekleme yapma.
   - İlettiğin her bilginin, şartın veya sayının sonuna mutlaka ilgili kaynak etiketini ekle: [belge_adi.pdf, s.X].

2. SORU KAPSAMINA SADAKAT (SCOPE ALIGNMENT):
   - Yalnızca kullanıcının doğrudan ve açıkça sorduğu konuyu yanıtla.
   - Kullanıcı özel bir alan/program belirtmedikçe, bağlamda geçen farklı program türlerine (özel geçişler, lisansüstü vb.) ait hükümleri genel kural gibi sıralama.
   - Soruyla doğrudan örtüşmeyen parçalardaki hükümleri yanıta dahil etme.

3. YETERSİZ BİLGİ VE KAPSAM DIŞI DURUMLAR (ABSTENTION):
   - Eğer sağlanan parçalarda sorunun doğrudan ve kesin bir karşılığı yer almıyorsa, bağlamdaki ilgisiz maddeleri zorlayarak cevap üretme.
   - Bu durumda doğrudan şu ifadeyi kullan:
     "Bu konu hakkında mevcut Kayseri Üniversitesi yönetmelik ve yönergelerinde bir bilgi bulunmamaktadır."

4. BİÇİM VE TON:
   - Tarafsız, kurumsal ve anlaşılır maddeli bir dil kullan."""

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

def filter_used_sources(answer: str, sources: list) -> list:
    """Yalnızca Gemini yanıtında açıkça [belge.pdf, s.X] olarak atıfta bulunulan parçaları filtreler."""
    citations = re.findall(r'\[([a-zA-Z0-9_\-]+\.pdf)(?:,\s*s\.?\s*(\d+))?\]', answer)
    if not citations:
        return []
    
    used = []
    seen = set()
    for c_file, c_page in citations:
        for s in sources:
            s_file = s.get("file")
            s_page = s.get("page")
            if s_file == c_file:
                if not c_page or int(c_page) == int(s_page):
                    key = (s_file, s_page)
                    if key not in seen:
                        seen.add(key)
                        used.append(s)
    return used

def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or "your_gemini_api_key" in api_key:
        return None
    from google import genai
    return genai.Client(api_key=api_key.strip())

def generate_answer(question: str, k: int = 6) -> dict:
    # 1. Arama sorgusunu genişletip en alakalı parçaları getir (BM25 + Vektör Hibrit)
    search_q = expand_query(question)
    results = search(search_q, k=k)
    
    sources = []
    context_parts = []
    for idx, (doc, meta, dist) in enumerate(results, 1):
        sources.append({
            "file": meta.get("file", "belge.pdf"),
            "page": meta.get("page", 1),
            "distance": round(float(dist), 3),
            "text": doc.strip()
        })
        context_parts.append(f"--- [Parça {idx} | Belge: {meta.get('file')} | Sayfa: {meta.get('page')}] ---\n{doc.strip()}")
    
    context_text = "\n\n".join(context_parts)
    
    user_prompt = f"""YÖNETMELİK VE YÖNERGE PARÇALARI:
{context_text}

ÖĞRENCİNİN SORUSU:
{question}

Lütfen yukarıdaki kurallara ve parçalara göre yanıtla:"""

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
            "sources": sources
        }

    # Modelleri dene (503 geçici yoğunluk için retry ile)
    last_error = None
    for model_name in CANDIDATE_MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.1}
                )
                if response.text:
                    ans = response.text.strip()
                    # SADECE cevapta geçen kaynakları filtrele
                    used_sources = filter_used_sources(ans, sources)
                    return {
                        "question": question,
                        "answer": ans,
                        "sources": used_sources,
                        "model": model_name
                    }
            except Exception as e:
                last_error = e
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(1.5)
                continue

    return {
        "question": question,
        "answer": f"API çağrısı sırasında bir hata oluştu: {str(last_error)}",
        "sources": []
    }

if __name__ == "__main__":
    test_q = sys.argv[1] if len(sys.argv) > 1 else "mezun olmam için kaç gano lazım"
    print(f"Soru: {test_q}\n")
    res = generate_answer(test_q)
    print("CEVAP:\n", res["answer"])
    print("\nKAYNAKLAR (Yalnızca Cevapta Kullanılanlar):")
    for s in res["sources"]:
        print(f"- [{s['file']}, s.{s['page']}] mesafe={s['distance']}")
