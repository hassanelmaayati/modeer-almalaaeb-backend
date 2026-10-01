from fastapi import APIRouter, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.tea import TeaModel
from models.user import UserModel

# Serializers
from serializers.tea import TeaSchema, CreateTeaSchema, UpdateTeaSchema
from typing import List
from dependencies.get_current_user import get_current_user

router = APIRouter(tags=["Teas Management"])


@router.get("/teas", response_model=List[TeaSchema])
def get_teas(db: Session = Depends(get_db)):
    teas = db.query(TeaModel).all()
    return teas


@router.get("/teas/{tea_id}", response_model=TeaSchema)
def get_teas(tea_id: int, db: Session = Depends(get_db)):
    tea = db.query(TeaModel).filter(TeaModel.id == tea_id).first()
    if not tea:
        raise HTTPException(status_code=404, detail="Tea not found")
    return tea


@router.post("/teas", response_model=TeaSchema, status_code=201)
def create_tea(
    tea: CreateTeaSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    try:
        new_tea = TeaModel(**tea.dict(), user_id=current_user.id)
        db.add(new_tea)
        db.commit()
        db.refresh(new_tea)
        return new_tea
    except:
        raise HTTPException(status_code=422, detail="Unprocessable Entity")


@router.put("/teas/{tea_id}", response_model=TeaSchema)
def update_tea(
    tea: UpdateTeaSchema,
    tea_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_tea = db.query(TeaModel).filter(TeaModel.id == tea_id).first()
    if not db_tea:
        raise HTTPException(status_code=404, detail="Tea not found")

    if db_tea.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this tea")

    tea_data = tea.dict(exclude_unset=True)
    for key, value in tea_data.items():
        setattr(db_tea, key, value)

    db.commit()
    db.refresh(db_tea)

    return db_tea


@router.delete("/teas/{tea_id}", status_code=204)
def delete_tea(
    tea_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_tea = db.query(TeaModel).filter(TeaModel.id == tea_id).first()
    if not db_tea:
        raise HTTPException(status_code=404, detail="Tea not found")
    if db_tea.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this tea")

    db.delete(db_tea)
    db.commit()
    # return {"message": f"Tea with ID {tea_id} has been deleted"}
    return None
