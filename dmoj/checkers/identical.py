from typing import Union
from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8bytes

try:
    from dmoj.checkers._checker import standard
except ImportError:
    # Fallback Python nếu không build được _checker.c
    def standard(judge_output: bytes, process_output: bytes) -> bool:
        judge = judge_output.strip()
        process = process_output.strip()
        return judge == process

def check(process_output: bytes, judge_output: bytes, pe_allowed: bool = True, **kwargs) -> Union[CheckerResult, bool]:
    if judge_output == process_output:
        return True
    feedback = None
    if pe_allowed and standard(utf8bytes(judge_output), utf8bytes(process_output)):
        feedback = 'Presentation Error, check your whitespace'
    return CheckerResult(False, 0, feedback=feedback)