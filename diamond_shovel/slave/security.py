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
_peer_keys: dict[str, tuple[ec.EllipticCurvePublicKey, int, int]] = {}

@inject
def init(run_context):
    global _private_key
    global _peer_keys
    with open(run_context["root"] / "keys" / "private_key.pem", "rb") as f:
        _private_key = serialization.load_pem_private_key(f.read(), None)

    public_key_path: pathlib.Path = run_context["root"] / "keys" / "peer"
    for key_file in public_key_path.iterdir():
        if not key_file.is_file():
            continue
        if not key_file.name.endswith(".pem"):
            continue
        with open(key_file, "rb") as f:
            _peer_keys[key_file.name] = serialization.load_pem_public_key(f.read()), 0, 0

async def validate_peer_signature(request: Request, x_signature: Annotated[str | None, Header()] = None):
    if len(_peer_keys) == 0:
        return
    if x_signature is None:
        raise HTTPException(status_code=403, detail="Invalid signature")

    verified = False
    for key_name, (key, verified_count, signed_count) in _peer_keys.items():
        sha = hashlib.sha256()
        sha.update(struct.pack("<I", verified_count))
        sha.update(request.url.path.encode("utf8"))
        sha.update(await request.body())
        result = sha.digest()
        try:
            key.verify(base64.b64decode(x_signature), result, ECDSA(Prehashed(SHA256())))
        except InvalidSignature:
            continue
        request.state.source = key_name
        verified = True
        _peer_keys[key_name] = key, verified_count + 1, signed_count
        break

    if not verified:
        raise HTTPException(status_code=403, detail="Invalid signature")

async def sign_response(request: Request, response: Response):
    yield

    key, verified_count, signed_count = _peer_keys[request.state.source]

    sha = hashlib.sha256()
    sha.update(struct.pack("<I", signed_count))
    sha.update(await response.body())
    result = sha.digest()
    response.headers['X-Signature'] = str(base64.b64encode(_private_key.sign(result, ECDSA(Prehashed(SHA256())))))
    _peer_keys[request.state.source] = key, signed_count + 1, signed_count
