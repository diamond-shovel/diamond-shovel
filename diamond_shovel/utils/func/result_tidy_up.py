from functools import wraps

import builtins
import logging


def dedup(lst):
    return list(set(lst))


def split_count(lst, count):
    return [lst[i::count] for i in range(count)]


def split_size(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]

def chained(func):
    def wrapper(target, *args, **kwargs):
        func(target, *args, **kwargs)
        return target
    return wrapper


builtins.dedup = dedup
builtins.split_count = split_count
builtins.split_size = split_size
builtins.chained = chained

def dedup_and_sort(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)

        def process(value):
            if isinstance(value, list):
                return dedup(value)
            return value

        if isinstance(result, tuple):
            return tuple(process(v) for v in result)
        else:
            return process(result)

    return wrapper


@dedup_and_sort
def example_function_single():
    return [3, 1, 2, 3, 1]


@dedup_and_sort
def example_function_multiple():
    return [3, 1, 2, 3, 1], [4, 5, 4, 6]


def example_function_single_no_sort():
    return [3, 1, 2, 3, 1]


def example_function_multiple_no_sort():
    return [3, 1, 2, 3, 1], [4, 5, 4, 6]


def example_int_return():
    return 123


def example_str_return():
    return 'abc'


@dedup_and_sort
def example_int_return_with_decorator():
    return 123


@dedup_and_sort
def example_str_return_with_decorator():
    return 'abc'

def example_kv_return():
    return {'a': 1, 'b': 2, 'c': 1, 'd': 2}

@dedup_and_sort
def example_kv_return_with_decorator():
    return {'a': 1, 'b': 2, 'c': 1, 'd': 2}


if __name__ == '__main__':
    logging.info(example_function_single_no_sort())
    logging.info(example_function_multiple_no_sort())
    logging.info('----以上为不排序的结果----')
    logging.info(example_function_single())
    logging.info(example_function_multiple())
    logging.info('----以上为排序的结果----')
    logging.info(example_int_return())
    logging.info(example_str_return())
    logging.info('----以上为不排序的结果----')
    logging.info(example_int_return_with_decorator())
    logging.info(example_str_return_with_decorator())
    logging.info('----以上为排序的结果----')
    logging.info(example_kv_return())
    logging.info(example_kv_return_with_decorator())
