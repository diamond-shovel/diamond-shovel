import base64
import json
import traceback

import dill


class ChainedJsonEncoder(json.JSONEncoder):
    def __init__(self, encoders: list[json.JSONEncoder] | None = None, **kwargs):
        super().__init__(**kwargs)
        if encoders is None:
            encoders = []
        self._encoders = [super(), encoders]

    def add_encoder(self, encoder: json.JSONEncoder):
        self._encoders.append(encoder)

    def remove_encoder(self, encoder: json.JSONEncoder):
        self._encoders.remove(encoder)

    def default(self, o):
        for encoder in self._encoders:
            try:
                return encoder.default(o)
            except TypeError:
                pass
        return super().default(o)


class EncodableObjectEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'jsonify'):
            return o.jsonify()
        return super().default(o)


class ExceptionEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Exception):
            return {
                '__exception__': True,
                'args': o.args,
                'message': str(o),
                'traceback': traceback.format_tb(o.__traceback__),
                'dill': base64.b64encode(dill.dumps(o)).decode('utf-8')
            }
        return super().default(o)