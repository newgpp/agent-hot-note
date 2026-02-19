from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to generate hot-note markdown for.")


class GenerateResponse(BaseModel):
    markdown: str
    meta: dict

