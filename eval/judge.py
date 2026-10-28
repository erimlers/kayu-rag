import json
import os
import time
from dotenv import load_dotenv

load_dotenv(override=True)

JUDGE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
]
_judge_rr = 0
ABSTENTION_MARKERS = (
    "bilgi bulunmamaktadır",
    "bilgi yer almamaktadır",
    "hüküm bulunmamaktadır",
)

JUDGE_SYSTEM_PROMPT = """Sen bağımsız bir Akademik Mevzuat Değerlendirme Hakemisin (LLM Judge).
Görevin: Öğrencinin sorusu, resmi referans doğru cevap (`dogru_cevap`) ve RAG asistanının ürettiği yanıtı karşılaştırarak yanıtın doğruluğunu nesnel biçimde sınıflandırmaktır.

SINIFLANDIRMA KURALLARI:
1. "dogru": Asistanın yanıtı, referans cevaptaki temel hükmü, sayısal sınırı veya şartı doğru biçimde içeriyor ve çelişen/yanlış bir bilgi içermiyor. (Ek doğru mevzuat bağlamı vermesi puan kırmaz).
2. "kismen": Asistan konuyla ilgili doğru maddeleri/kuralları aktarmış ancak referans cevaptaki spesifik bir detayı eksik bırakmış veya kısmi bilgi vermiş.
3. "yanlis": Asistan referans cevapla çelişen bir sayı/kural söylemiş, sorulan konuyla ilgisiz başka bir yönergeyi sorunun cevabıymış gibi sunmuş veya cevabı olan soruya "bilgi bulunmamaktadır" demiş.

Yalnızca aşağıdaki JSON formatında yanıt ver:
{
  "verdict": "dogru" | "kismen" | "yanlis",
  "reason": "tek cümlelik kısa gerekçe"
}"""


def is_abstention_text(answer: str) -> bool:
    low = answer.lower()
    if any(m in low for m in ABSTENTION_MARKERS):
        # Eğer sadece abstention cümlesi varsa veya kaynak göstermeden bilgi olmadığını söylüyorsa
        if len(answer.strip()) < 220:
            return True
    return False


def judge_answer(question: str, expected_answer: str, system_answer: str, is_unanswerable: bool = False) -> dict:
    abstained = is_abstention_text(system_answer)

    if is_unanswerable:
        # Cevapsız sorularda doğru davranış abstention yapmaktır
        correct_abstention = abstained or (
            any(m in system_answer.lower() for m in ABSTENTION_MARKERS)
        )
        return {
            "abstained": correct_abstention,
            "verdict": "dogru" if correct_abstention else "yanlis",
            "wrong_confident": not correct_abstention,
            "reason": "Kapsam dışı soruda doğru biçimde çekimser kaldı." if correct_abstention else "Kapsam dışı soruya kaynak/kural uydurarak yanıt verdi."
        }

    # Cevaplı soruda tamamen "bilgi bulunmamaktadır" dediyse doğrudan gereksiz abstention (yanlış)
    if abstained:
        return {
            "abstained": True,
            "verdict": "yanlis",
            "wrong_confident": False,
            "reason": "Belgelerde cevabı olan soruya bilgi bulunmamaktadır dedi (gereksiz abstention)."
        }

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or "your_gemini_api_key" in api_key:
        return {
            "abstained": False,
            "verdict": "belirsiz",
            "wrong_confident": False,
            "reason": "API anahtarı yok"
        }

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"timeout": 20000})
    prompt = f"""SORU: {question}
REFERANS DOĞRU CEVAP: {expected_answer}
ASİSTANIN YANITI: {system_answer}"""

    global _judge_rr
    start_idx = _judge_rr % len(JUDGE_MODELS)
    _judge_rr += 1
    ordered_models = JUDGE_MODELS[start_idx:] + JUDGE_MODELS[:start_idx]

    for round_num in range(2):
        for model_name in ordered_models:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=JUDGE_SYSTEM_PROMPT,
                        temperature=0.0,
                        max_output_tokens=200,
                        response_mime_type="application/json",
                    ),
                )
                data = json.loads(resp.text.strip())
                verdict = data.get("verdict", "yanlis")
                if verdict not in ("dogru", "kismen", "yanlis"):
                    verdict = "yanlis"
                return {
                    "abstained": False,
                    "verdict": verdict,
                    "wrong_confident": verdict == "yanlis",
                    "reason": data.get("reason", "")
                }
            except Exception as e:
                err_s = str(e)
                if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s:
                    time.sleep(1.2)
                    continue
                if "503" in err_s:
                    time.sleep(1.5)
                continue
        time.sleep(3.0)

    return {
        "abstained": False,
        "verdict": "yanlis",
        "wrong_confident": True,
        "reason": "Judge API hatası"
    }

