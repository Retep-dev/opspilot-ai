"""OIDC bearer-token verification and database-backed role lookup."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import jwt
import psycopg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.observability import set_tenant
from app.service import Actor

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class OidcSettings:
    issuer: str
    audience: str
    jwks_url: str


class TokenVerifier:
    def __init__(self, settings: OidcSettings) -> None:
        self.settings = settings
        self.jwks = jwt.PyJWKClient(settings.jwks_url, cache_jwk_set=True, lifespan=300)

    def verify(self, token: str) -> tuple[str, UUID]:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.settings.audience,
            issuer=self.settings.issuer,
            options={"require": ["exp", "iat", "sub", "tenant_id"]},
        )
        return str(claims["sub"]), UUID(claims["tenant_id"])


async def get_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Actor:
    verifier: TokenVerifier | None = getattr(request.app.state, "token_verifier", None)
    database_url: str | None = getattr(request.app.state, "database_url", None)
    if verifier is None or database_url is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    try:
        subject, tenant_id = await asyncio.to_thread(
            verifier.verify, credentials.credentials
        )
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid bearer token") from None
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        cursor = await conn.execute(
            """SELECT id, role FROM users
               WHERE tenant_id = %s AND identity_subject = %s""",
            (tenant_id, subject),
        )
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="User is not provisioned")
    set_tenant(str(tenant_id))
    return Actor(user_id=row[0], tenant_id=tenant_id, role=row[1])


def require_roles(*roles: str):
    async def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return actor

    return dependency
