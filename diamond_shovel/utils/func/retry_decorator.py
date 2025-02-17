import functools
import time
import logging
import traceback


def retry(max_retries=3, delay=1):
    """
    重试装饰器

    参数:
    max_retries (int): 最大重试次数。
    delay (int): 重试间隔时间（秒）。
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception:
                    attempts += 1
                    if attempts >= max_retries:
                        logging.error(f"Routine failed after {attempts} attempts.")
                        raise
                    logging.warning(f"Routine failed. Retrying in {delay} seconds.")
                    logging.warning(f"{traceback.format_exc()}")
                    time.sleep(delay)

        return wrapper

    return decorator
