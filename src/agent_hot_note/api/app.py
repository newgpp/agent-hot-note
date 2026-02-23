import logging

from fastapi import FastAPI

from agent_hot_note.api.schemas import GenerateRequest, GenerateResponse
from agent_hot_note.service.generator import GenerateService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="agent-hot-note", version="0.1.0")
service = GenerateService()


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    result = await service.generate(req.topic, topic_profile=req.topic_profile)
    return GenerateResponse(**result)
