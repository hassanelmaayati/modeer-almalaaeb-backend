"""Normalize account uniqueness races without hiding other database failures."""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


def unique_constraint(error: IntegrityError) -> str | None:
    original = error.orig
    if getattr(original, 'pgcode', None) != '23505':
        return None
    return getattr(getattr(original, 'diag', None), 'constraint_name', '')


def commit_account(db, *, email_status=400, google_status=409):
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        constraint = unique_constraint(error)
        if constraint is None:
            raise
        if constraint == 'users_user_name_key':
            raise HTTPException(400, 'user name is already taken') from error
        if constraint == 'users_email_key':
            raise HTTPException(email_status, 'Email is already registered') from error
        if constraint == 'users_google_subject_key':
            raise HTTPException(google_status, 'This Google account is linked to another user') from error
        raise HTTPException(409, 'This account change conflicts with existing data') from error
