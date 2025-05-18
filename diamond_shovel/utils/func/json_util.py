import base64
import json
import traceback

import dill


class ExtensibleEncoder(json.JSONEncoder):
    def __init__(self, **kwargs):
        super(ExtensibleEncoder, self).__init__(**kwargs)
        self._transformers = {}

    def default(self, o):
        for k, v in self._transformers.items():
            if isinstance(o, k):
                return v(o)
        return super().default(o)

_extensible_encoder = ExtensibleEncoder()

def get_encoder():
    return _extensible_encoder

def put_encoder(t, encoder):
    _extensible_encoder._transformers[t] = encoder


put_encoder(Exception, lambda o: {
    '__exception__': True,
    'args': o.args,
    'message': str(o),
    'traceback': traceback.format_tb(o.__traceback__),
    'dill': base64.b64encode(dill.dumps(o)).decode('utf-8')
})
