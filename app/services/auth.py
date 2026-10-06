import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ApplicationError
from app.core.security import (
    AuthenticationError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


async def register_user(
    session: AsyncSession,
    registration: RegisterRequest,
) -> User:
    email = str(registration.email).lower()
    existing_user = await session.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        raise ApplicationError(
            "A user with this email already exists",
            code="email_already_registered",
            status_code=409,
        )

    hashed_password = await asyncio.to_thread(
        hash_password,
        registration.password.get_secret_value(),
    )
    user = User(
        email=email,
        hashed_password=hashed_password,
        display_name=registration.display_name,
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "A user with this email already exists",
            code="email_already_registered",
            status_code=409,
        ) from exc

    await session.refresh(user)
    return user


async def authenticate_user(
    session: AsyncSession,
    credentials: LoginRequest,
) -> User:
    email = str(credentials.email).lower()
    user = await session.scalar(select(User).where(User.email == email))
    password = credentials.password.get_secret_value()

    if user is None:
        await asyncio.to_thread(hash_password, password)
        raise AuthenticationError("Invalid email or password")

    password_is_valid = await asyncio.to_thread(
        verify_password,
        password,
        user.hashed_password,
    )
    if not password_is_valid or not user.is_active:
        raise AuthenticationError("Invalid email or password")
    return user


def issue_token_pair(user: User, settings: Settings) -> TokenPair:
    return TokenPair(
        access_token=create_token(user.id, "access", settings),
        refresh_token=create_token(user.id, "refresh", settings),
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def get_user_for_token(
    session: AsyncSession,
    token: str,
    token_type: TokenType,
    settings: Settings,
) -> User:
    user_id = decode_token(token, token_type, settings)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError()
    return user


async def refresh_tokens(
    session: AsyncSession,
    refresh_token: str,
    settings: Settings,
) -> TokenPair:
    user = await get_user_for_token(session, refresh_token, "refresh", settings)
    return issue_token_pair(user, settings)
