import base64
import hashlib
import pathlib
import struct
from typing import Annotated

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import HTTPException, Request
from fastapi.openapi.models import Response
from fastapi.params import Header
from kink import inject

_private_key: ec.EllipticCurvePrivateKey
_peer_public_key: ec.EllipticCurvePublicKey | None = None

verified_count = 0
signed_count = 0

@inject
def init(run_context):
    global _private_key
    global _peer_public_key
    with open(run_context["root"] / "keys" / "private_key.pem", "rb") as f:
        _private_key = serialization.load_pem_private_key(f.read(), None)

    public_key_path: pathlib.Path = run_context["root"] / "keys" / "peer_key.pem"
    if public_key_path.exists():
        with open(public_key_path, "rb") as f:
            _peer_public_key = serialization.load_pem_public_key(f.read())
    else:
        # TODO: add a warning message, i don't have any input method yet
        pass

async def validate_peer_signature(request: Request, x_signature: Annotated[str | None, Header()] = None):
    global verified_count

    if _peer_public_key is None:
        return
    if x_signature is None:
        raise HTTPException(status_code=403, detail="Invalid signature")

    sha = hashlib.sha256()
    sha.update(struct.pack("<I", verified_count))
    sha.update(request.url.path.encode("utf8"))
    sha.update(await request.body())
    result = sha.digest()
    try:
        _peer_public_key.verify(base64.b64decode(x_signature), result, ECDSA(Prehashed(SHA256())))
    except InvalidSignature:
        raise HTTPException(status_code=403, detail="Invalid signature")
    verified_count += 1

async def sign_response(response: Response):
    global signed_count
    yield

    sha = hashlib.sha256()
    sha.update(struct.pack("<I", signed_count))
    sha.update(await response.body())
    result = sha.digest()
    response.headers['X-Signature'] = str(base64.b64encode(_private_key.sign(result, ECDSA(Prehashed(SHA256())))))
    signed_count += 1
