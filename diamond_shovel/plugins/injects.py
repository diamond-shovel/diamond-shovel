import functools
import inspect

from kink import inject as inj


# idk why this must work with diamond_shovel.plugins.plugins.PluginInitContext.attach
# removing either of them could break the shovel down.
# maybe the policy of python object reference is in our way.
def inject(func):
    """
    Works as same with kink.di
    """
    for f in inspect.stack():
        if "plugin_context" in f[0].f_locals:
            ctx = f[0].f_locals["plugin_context"]
            break
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        decorator = inj(container=ctx.fetch_current_container())
        return decorator(func)(*args, **kwargs)
    return wrapper
