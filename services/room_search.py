from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_GeogFromText
from sqlalchemy.orm import Session

from models.room import RoomModel, make_point


# Open rooms whose venue pin is within radius_m metres of a point, nearest first.
# PostgreSQL + PostGIS only. The pin is the private venue location, so this must
# not back a public endpoint: sorting or filtering by distance would reveal it.
def rooms_near(
    db: Session, latitude: float, longitude: float, radius_m: float
) -> list[RoomModel]:
    origin = ST_GeogFromText(make_point(latitude, longitude))
    return (
        db.query(RoomModel)
        .filter(
            RoomModel.status == "open",
            RoomModel.venue_point.isnot(None),
            ST_DWithin(RoomModel.venue_point, origin, radius_m),
        )
        .order_by(ST_Distance(RoomModel.venue_point, origin))
        .all()
    )
