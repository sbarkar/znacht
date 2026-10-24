from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """Base for all domain models: immutable, strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
