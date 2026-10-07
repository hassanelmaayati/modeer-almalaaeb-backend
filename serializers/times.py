from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator


def to_aware_utc(value: datetime) -> datetime:
    # Naive values in the database are UTC; aware ones are converted, so every
    # response says +00:00 whatever timezone the database server uses
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UtcOutput = Annotated[datetime, AfterValidator(to_aware_utc)]
