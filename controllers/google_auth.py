import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from config.environment import GOOGLE_CLIENT_ID
from database import get_db
from dependencies.get_current_user import get_current_user
from models.user import UserModel
from serializers.user import GoogleCredentialSchema, UserSchema, UserTokenSchema

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

    new_user = UserModel(
        user_name=unique_user_name(db, email),
        email=email,
        photo_url=claims.get("picture"),
        google_subject=subject,
    )
    # Password is required on User; a hash of a discarded random secret means
    # password sign-in can never succeed for a Google-only account
    new_user.set_password(secrets.token_urlsafe(32))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    response.status_code = 201
    token = new_user.generate_jwt()
    return {"token": token, "msg": "User registered successfully", "user": new_user}


@router.post("/auth/google/link", response_model=UserSchema)
def link_google(
    google: GoogleCredentialSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    claims = verify_google_credential(google.credential)
    subject = claims["sub"]

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
    db.commit()
    db.refresh(current_user)
    return current_user
