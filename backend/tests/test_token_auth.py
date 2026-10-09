from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import OidcSettings, TokenVerifier


def test_oidc_verifier_accepts_signed_claims_and_rejects_wrong_audience() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tenant_id = uuid4()
    verifier = TokenVerifier(
        OidcSettings(
            "https://issuer.example", "opspilot-api", "https://issuer.example/jwks"
        )
    )
    verifier.jwks.get_signing_key_from_jwt = lambda token: SimpleNamespace(
        key=private_key.public_key()
    )
    claims = {
        "iss": "https://issuer.example",
        "aud": "opspilot-api",
        "sub": "user-1",
        "tenant_id": str(tenant_id),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")
    assert verifier.verify(token) == ("user-1", tenant_id)
    claims["aud"] = "other-api"
    with pytest.raises(jwt.InvalidAudienceError):
        verifier.verify(jwt.encode(claims, private_key, algorithm="RS256"))
