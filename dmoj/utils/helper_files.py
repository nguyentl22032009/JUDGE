import os
import subprocess
import tempfile
from typing import IO, List, Optional, Sequence, TYPE_CHECKING

from dmoj.error import InternalError
from dmoj.result import Result

if TYPE_CHECKING:
    from dmoj.executors.base_executor import BaseExecutor

def mktemp(data: bytes) -> IO:
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(data)
    tmp.flush()
    return tmp

def compile_with_auxiliary_files(
    filenames: Sequence[str],
    flags: List[str] = [],
    lang: Optional[str] = None,
    compiler_time_limit: Optional[int] = None,
    unbuffered: bool = False,
) -> 'BaseExecutor':
    from dmoj import executors
    from dmoj.executors.compiled_executor import CompiledExecutor

    sources = {}
    for filename in filenames:
        with open(filename, 'rb') as f:
            sources[os.path.basename(filename)] = f.read()

    def find_runtime(*languages):
        for grader in languages:
            if grader in executors.executors:
                return grader
        return None

    use_cpp = any(map(lambda name: os.path.splitext(name)[1] in ['.cpp', '.cc'], filenames))
    use_c = any(map(lambda name: os.path.splitext(name)[1] in ['.c'], filenames))
    if not lang:
        if use_cpp:
            lang = find_runtime('CPP20', 'CPP17', 'CPP14', 'CPP11', 'CPP03')
        elif use_c:
            lang = find_runtime('C11', 'C')

    if not lang:
        for filename in filenames:
            try:
                lang = executors.from_filename(filename).Executor.name
            except KeyError:
                continue

    if not lang:
        raise IOError('could not find an appropriate executor')

    executor = executors.executors[lang].Executor

    kwargs = {'fs': executor.fs + [tempfile.gettempdir()]}  # Thay RecursiveDir bằng đường dẫn tạm

    if issubclass(executor, CompiledExecutor):
        kwargs['compiler_time_limit'] = compiler_time_limit

    if hasattr(executor, 'flags'):
        kwargs['flags'] = flags + list(executor.flags)

    if use_cpp or use_c:
        executor = executor('_aux_file', None, aux_sources=sources, cached=True, unbuffered=unbuffered, **kwargs)
    else:
        if len(sources) > 1:
            raise InternalError('non-C/C++ auxiliary programs cannot be multi-file')
        executor = executor('_aux_file', list(sources.values())[0], cached=True, unbuffered=unbuffered, **kwargs)

    return executor

def parse_helper_file_error(
    proc: 'subprocess.Popen', executor: 'BaseExecutor', name: str, stderr: bytes, time_limit: float, memory_limit: int
) -> None:
    # Không có cptbox, dùng logic đơn giản để kiểm tra lỗi
    if proc.returncode is None:  # Process chưa hoàn thành
        error = f'{name} timed out (> {time_limit} seconds)'
    elif proc.returncode != 0:
        if proc.returncode > 0:
            error = f'{name} exited with nonzero code {proc.returncode}'
        else:
            error = f'{name} terminated with signal {-proc.returncode}'
        feedback = Result.get_feedback_str(stderr, proc, executor)
        if feedback:
            error += f' with feedback {feedback}'
    else:
        return

    raise InternalError(error)