from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from models.cup import CUP_FORMATS


class SportSchema(BaseModel):
    id: int
    name: str
    # Fixed team formats such as [{"key": "5v5", "capacity": 10}]; empty for sports with any capacity
    formats: list[dict] | None = None

    model_config = ConfigDict(from_attributes=True)

    # Same lookup cups use, so the frontend knows which cup form to show; null means no cups
    @computed_field
    @property
    def cup_format(self) -> Literal["knockout", "race"] | None:
        return CUP_FORMATS.get(self.name.strip().lower())
