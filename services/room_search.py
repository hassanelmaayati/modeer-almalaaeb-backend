"""Distance search over venue pins.

A venue pin is private: only the host and admitted players may see it. A public
search that filters or sorts by the distance to the exact pin would give it away
by trilateration (ask "within r km of P" from several points while shrinking r).
So the public filter (near_filters) measures to the pin snapped to a coarse grid
of about 2 km, which can only reveal that cell, no more than the public area name.
rooms_near keeps the exact pin and is for internal use, never for a public endpoint.
"""
from geoalchemy2 import Geography, Geometry
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_GeogFromText
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from models.room import RoomModel, make_point


GRID_DEGREES = 0.02
GRID_MARGIN_M = 3000


def near_filters(latitude: float, longitude: float, radius_km: float):
    """(distance in metres to the coarse venue point, conditions) for the public ?near_ filter."""
    origin = ST_GeogFromText(make_point(latitude, longitude))
    coarse = cast(func.ST_SnapToGrid(cast(RoomModel.venue_point, Geometry), GRID_DEGREES), Geography)
    metres = ST_Distance(coarse, origin)
    radius_m = radius_km * 1000
    return metres, [
        RoomModel.venue_point.is_not(None),
        # The spatial index narrows the search; the exact test uses the coarse point
        ST_DWithin(RoomModel.venue_point, origin, radius_m + GRID_MARGIN_M),
        metres <= radius_m,
    ]


# Open rooms whose EXACT venue pin is within radius_m metres of a point, nearest first.
# PostgreSQL + PostGIS only. Internal use only (see the module note): a public
# endpoint must use near_filters instead.
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
