import abc
import base64
import json
import traceback

import dill


class JsonExportable(abc.ABC):
    @abc.abstractmethod
    def export(self):
        ...

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
        if isinstance(o, JsonExportable):
            return o.export()
        return super().default(o)