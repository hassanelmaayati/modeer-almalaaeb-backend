from fastapi import APIRouter, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.sport import SportModel

# Serializers
from serializers.sport import SportSchema
from typing import List

router = APIRouter(
    tags=[
        "Sports Management",
    ]
)


@router.get("/sports", response_model=List[SportSchema])
def get_sports(db: Session = Depends(get_db)):
    return db.query(SportModel).all()


@router.get("/sports/{sport_id}", response_model=SportSchema)
def get_sport(sport_id: int, db: Session = Depends(get_db)):
    sport = db.query(SportModel).filter(SportModel.id == sport_id).first()
    if not sport:
        raise HTTPException(status_code=404, detail="Sport not found")
    return sport
