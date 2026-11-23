import json, os, sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Proje kök dizinini ekle
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
import mini_rag
from src.generate import generate_answer, generate_answer_stream


def _find_logo_path() -> Path | None:
    try:
        for p in ROOT_DIR.iterdir():
            if p.is_file() and "logo" in p.name.lower() and p.suffix.lower() in {".jpeg", ".jpg", ".png"}:
                return p
    except Exception:
        pass
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    mini_rag.warmup()
    yield


app = FastAPI(title="KAYÜ RAG Asistanı API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".css", ".js")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class AskRequest(BaseModel):
    question: str


@app.get("/api/logo")
def api_logo():
    logo_path = _find_logo_path()
    if logo_path is None:
        return Response(status_code=404)
    return FileResponse(
        logo_path,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/ask")
def api_ask(req: AskRequest):
    q = req.question.strip()
    if not q:
        return {"error": "Lütfen bir soru giriniz."}
    return generate_answer(q)


@app.post("/api/ask/stream")
def api_ask_stream(req: AskRequest):
    q = req.question.strip()

    def event_stream():
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Lütfen bir soru giriniz.'}, ensure_ascii=False)}\n\n"
            return
        for event in generate_answer_stream(q, k=6):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
def api_health():
    return {"status": "ok", "service": "kayu-rag"}


# Web arayüzünü sun (web klasörü varsa)
web_dir = ROOT_DIR / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
