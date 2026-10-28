import os, sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.generate import generate_answer

app = FastAPI(title="KAYÜ RAG Asistanı API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str

@app.post("/api/ask")
def api_ask(req: AskRequest):
    q = req.question.strip()
    if not q:
        return {"error": "Lütfen bir soru giriniz."}
    return generate_answer(q)

@app.get("/api/health")
def api_health():
    return {"status": "ok", "service": "kayu-rag"}

# Web arayüzünü sun (web klasörü varsa)
web_dir = Path(__file__).resolve().parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
