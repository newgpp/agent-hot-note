from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to generate hot-note markdown for.")
    topic_profile: str | None = Field(
        default=None,
        description="Optional profile override, e.g. general/job/finance.",
    )


class GenerateResponse(BaseModel):
    markdown: str
    meta: dict
