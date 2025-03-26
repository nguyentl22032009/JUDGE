from typing import Callable
from ..utils.unicode import utf8bytes

try:
    from .checker import standard
except ImportError:
    # Fallback Python nếu không build được _checker.c
    def standard(judge_output: bytes, process_output: bytes) -> bool:
        judge = judge_output.strip()
        process = process_output.strip()
        return judge == process

def check(
    process_output: bytes, judge_output: bytes, _checker: Callable[[bytes, bytes], bool] = standard, **kwargs
) -> bool:
    return _checker(utf8bytes(judge_output), utf8bytes(process_output))

del standard