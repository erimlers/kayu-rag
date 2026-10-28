import json
import os
import pathlib
import threading
from dotenv import load_dotenv

load_dotenv(override=True)

CACHE_PATH = pathlib.Path("db/rewrite_cache.json")
REWRITE_MODEL = "gemini-3.5-flash-lite"
_LOCK = threading.RLock()
_MEM_CACHE = None

REWRITE_SYSTEM_PROMPT = """Sen bir üniversite mevzuat arama motoru için Sorgu Yeniden Yazma (Query Rewriting) modülüsün.
Görevin: Öğrencinin yazdığı kısa, devrik, yazım hatalı veya günlük konuşma dilindeki ifadeyi, üniversite yönetmelik ve yönergelerinde geçen resmi mevzuat terminolojisine dönüştürmektir.

KESİN KURALLAR:
1. ASLA sayı, oran, gün, puan veya kural uydurma (ör. sorguda geçmeyen bir notu veya süreyi ekleme).
2. Yalnızca öğrencinin sorduğu kavramın resmi mevzuat karşılıklarını içeren 2 adet arama ifadesi üret.
3. Yazım hatalarını ve Türkçe karakter eksiklerini düzelt.
4. Tek kelimelik veya yarım bırakılmış ifadeleri ("kayıt yenileme", "diploma kaybı", "bütünleme") o konudaki temel mevzuat kurallarını (şartlar, uygulama esasları, başarısızlık durumu, süreler) arayacak tam birer mevzuat arama cümlesine dönüştür.
5. Sorgunun hitap ettiği öğrenim düzeyini belirle:
   - Sorguda yüksek lisans, doktora, tez, enstitü, yeterlik, seminer, bilimsel hazırlık geçiyorsa: "lisansustu"
   - Sorguda ön lisans, lisans, çift anadal, yandal, intibak, yaz okulu, işletmede mesleki eğitim, staj, muafiyet sınavı geçiyorsa: "onlisans_lisans"
   - Öğrenim düzeyi belirtilmemişse (genel öğrenci sorusuysa): "genel"

Yalnızca aşağıdaki JSON şemasında yanıt ver:
{
  "program_level": "onlisans_lisans" | "lisansustu" | "genel",
  "rewritten_queries": ["resmi arama sorgusu 1", "resmi arama sorgusu 2"]
}"""


def _load_cache() -> dict:
    global _MEM_CACHE
    with _LOCK:
        if _MEM_CACHE is not None:
            return _MEM_CACHE
        if CACHE_PATH.exists():
            try:
                _MEM_CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                return _MEM_CACHE
            except Exception:
                _MEM_CACHE = {}
                return _MEM_CACHE
        _MEM_CACHE = {}
        return _MEM_CACHE


def _save_cache_entry(key: str, val: dict) -> None:
    with _LOCK:
        cache = _load_cache()
        cache[key] = val
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def fallback_rewrite(query: str) -> dict:
    q_low = query.lower()
    grad_terms = ("lisansüstü", "lisansustu", "yüksek lisans", "yuksek lisans", "doktora", "tez", "tezli", "tezsiz", "enstitü", "enstitu", "seminer", "yeterlik")
    level = "lisansustu" if any(t in q_low for t in grad_terms) else "genel"
    return {
        "program_level": level,
        "rewritten_queries": []
    }


def rewrite_query(query: str, use_llm: bool = True) -> dict:
    q_clean = query.strip()
    if not q_clean or not use_llm:
        return fallback_rewrite(q_clean)

    cache = _load_cache()
    if q_clean in cache:
        return cache[q_clean]

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or "your_gemini_api_key" in api_key:
        return fallback_rewrite(q_clean)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options={"timeout": 15000})
        resp = client.models.generate_content(
            model=REWRITE_MODEL,
            contents=f"Öğrenci sorgusu: {q_clean}",
            config=types.GenerateContentConfig(
                system_instruction=REWRITE_SYSTEM_PROMPT,
                temperature=0.0,
                max_output_tokens=200,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(resp.text.strip())
        level = data.get("program_level", "genel")
        if level not in ("onlisans_lisans", "lisansustu", "genel"):
            level = "genel"
        rq = [str(x).strip() for x in data.get("rewritten_queries", []) if str(x).strip()][:2]
        result = {"program_level": level, "rewritten_queries": rq}
        _save_cache_entry(q_clean, result)
        return result
    except Exception:
        return fallback_rewrite(q_clean)
