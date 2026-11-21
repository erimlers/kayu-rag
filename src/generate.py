import os, sys, time, re
from pathlib import Path
from dotenv import load_dotenv

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mini_rag import search

# .env dosyasını yükle
load_dotenv(override=True)

# Sabit birincil model + yalnızca kota/erişim hatasında fallback (round-robin yok)
MODEL_ORDER = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
]

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
   - Tarafsız, kurumsal ve anlaşılır maddeli bir dil kullan."""


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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or "your_gemini_api_key" in api_key:
        return None
    from google import genai
    return genai.Client(api_key=api_key.strip(), http_options={"timeout": 30000})


def generate_answer(question: str, k: int = 6, use_rewrite: bool = True, precomputed_results=None) -> dict:
    results = precomputed_results if precomputed_results is not None else search(question, k=k, use_rewrite=use_rewrite)

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
            "sources": sources,
            "citation_audit": {"total": 0, "verified": 0, "unverified": []},
        }

    last_error = None
    for round_num in range(2):
        for model_name in MODEL_ORDER:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.1}
                )
                if response.text:
                    ans = clean_abstention_contradiction(response.text)
                    used_sources, citation_audit = verify_and_filter_sources(ans, sources)
                    return {
                        "question": question,
                        "answer": ans,
                        "sources": used_sources,
                        "citation_audit": citation_audit,
                        "model": model_name,
                    }
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(1.2)
                    continue
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(1.5)
                continue
        time.sleep(2.5)

    return {
        "question": question,
        "answer": f"API çağrısı sırasında bir hata oluştu: {str(last_error)}",
        "sources": [],
        "citation_audit": {"total": 0, "verified": 0, "unverified": []},
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
