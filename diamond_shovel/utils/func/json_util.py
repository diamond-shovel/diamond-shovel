import base64
import json
import traceback

import dill


class ExceptionExtendedEncoder(json.JSONEncoder):
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