import random
import uuid


def generate_uuid(seed: str):
    r = random.Random(seed)
    return uuid.UUID(int=r.getrandbits(128), version=4)
