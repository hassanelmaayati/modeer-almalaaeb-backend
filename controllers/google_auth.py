import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.environment import GOOGLE_CLIENT_ID
from database import get_db
from dependencies.get_current_user import get_current_user
from models.user import UserModel
from serializers.user import GoogleCredentialSchema, UserPrivateSchema, UserTokenSchema
from services.accounts import commit_account, unique_constraint

router = APIRouter(tags=["Auth"])


def verify_google_credential(credential: str) -> dict:
    # Without a client ID the audience check is skipped, which would accept
    # tokens issued to any other app, so refuse instead
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            Request(),
            GOOGLE_CLIENT_ID,
            # Small allowance for clock drift between our server and Google
            clock_skew_in_seconds=10,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    except GoogleAuthError:
        # Google's signing keys could not be fetched; not the user's fault
        raise HTTPException(
            status_code=503, detail="Could not reach Google, please try again"
        )

    # An unverified email could belong to someone else, so never trust it
    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google email is not verified")

    return claims


def unique_user_name(db: Session, email: str) -> str:
    # Start from the part before the @ and keep the 3-60 length used at signup
    base = email.split("@")[0][:50]
    if len(base) < 3:
        base = f"{base}_player"

    user_name = base
    number = 2
    while db.query(UserModel).filter(UserModel.user_name == user_name).first():
        user_name = f"{base}{number}"
        number += 1
    return user_name


@router.post("/auth/google", response_model=UserTokenSchema)
def google_sign_in(
    google: GoogleCredentialSchema,
    response: Response,
    db: Session = Depends(get_db),
):
    claims = verify_google_credential(google.credential)
    subject = claims["sub"]
    email = claims["email"].strip().lower()

    db_user = db.query(UserModel).filter(UserModel.google_subject == subject).first()
    if db_user:
        token = db_user.generate_jwt()
        return {"token": token, "msg": "Login successful", "user": db_user}

    # Signing in with Google must not take over an existing password account;
    # its owner has to prove the password first and then link Google
    if db.query(UserModel).filter(UserModel.email == email).first():
        raise HTTPException(
            status_code=409,
            detail="Sign in with your password, then link Google in Settings",
        )

    # Password is required on User; a hash of a discarded random secret means
    # password sign-in can never succeed for a Google-only account
    password = secrets.token_urlsafe(32)
    for attempt in range(3):
        new_user = UserModel(
            user_name=unique_user_name(db, email),
            email=email,
            photo_url=claims.get("picture"),
            google_subject=subject,
        )
        new_user.set_password(password)
        db.add(new_user)
        try:
            db.commit()
            break
        except IntegrityError as error:
            db.rollback()
            constraint = unique_constraint(error)
            if constraint is None:
                raise
            # Another request may have completed the same Google sign-in.
            existing = db.query(UserModel).filter(UserModel.google_subject == subject).first()
            if existing:
                return {"token": existing.generate_jwt(), "msg": "Login successful", "user": existing}
            if db.query(UserModel).filter(UserModel.email == email).first():
                raise HTTPException(409, "Sign in with your password, then link Google in Settings") from error
            # Different Google users can share the same email prefix. Regenerate
            # the public name after the winning transaction becomes visible.
            if constraint != 'users_user_name_key' or attempt == 2:
                raise HTTPException(409, "Account creation conflicted, please try again") from error
    db.refresh(new_user)

    response.status_code = 201
    token = new_user.generate_jwt()
    return {"token": token, "msg": "User registered successfully", "user": new_user}


@router.post("/auth/google/link", response_model=UserPrivateSchema)
def link_google(
    google: GoogleCredentialSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    claims = verify_google_credential(google.credential)
    subject = claims["sub"]

    # Refresh under a row lock: simultaneous links to this account cannot
    # overwrite the first accepted Google identity.
    current_user = db.query(UserModel).filter(UserModel.id == current_user.id).with_for_update().populate_existing().one()

    # One Google account can only sign in to one of our users
    owner = db.query(UserModel).filter(UserModel.google_subject == subject).first()
    if owner and owner.id != current_user.id:
        raise HTTPException(
            status_code=400, detail="This Google account is linked to another user"
        )

    if current_user.google_subject:
        raise HTTPException(
            status_code=409, detail="Google is already linked to your account"
        )

    current_user.google_subject = subject
    commit_account(db, google_status=400)
    db.refresh(current_user)
    return current_user
