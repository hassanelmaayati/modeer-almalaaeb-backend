from pydantic import BaseModel, ConfigDict


class SportSchema(BaseModel):
    id: int
    name: str
    # Fixed team formats such as [{"key": "5v5", "capacity": 10}]; empty for sports with any capacity
    formats: list[dict] | None = None

    model_config = ConfigDict(from_attributes=True)
