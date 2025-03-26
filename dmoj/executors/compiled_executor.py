import hashlib
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import pylru

from dmoj.error import CompileError, OutputLimitExceeded
from dmoj.executors.base_executor import BaseExecutor, ExecutorMeta
from dmoj.judgeenv import env
from dmoj.utils.communicate import safe_communicate
from dmoj.utils.unicode import utf8bytes

class _CompiledExecutorMeta(ExecutorMeta):
    @staticmethod
    def _cleanup_cache_entry(_key, executor: 'CompiledExecutor') -> None:
        executor.is_cached = False

    compiled_binary_cache: Dict[str, 'CompiledExecutor'] = pylru.lrucache(
        env.compiled_binary_cache_size, _cleanup_cache_entry
    )

    def __call__(cls, *args, **kwargs) -> 'CompiledExecutor':
        is_cached: bool = kwargs.pop('cached', False)
        if is_cached:
            kwargs['dest_dir'] = env.compiled_binary_cache_dir
        obj: 'CompiledExecutor' = super().__call__(*args, **kwargs)
        obj.is_cached = is_cached

        if is_cached:
            cache_key_material = utf8bytes(obj.__class__.__name__ + obj.__module__) + obj.get_binary_cache_key()
            cache_key = hashlib.sha384(cache_key_material).hexdigest()
            if cache_key in cls.compiled_binary_cache:
                executor = cls.compiled_binary_cache[cache_key]
                assert executor._executable is not None
                if os.path.isfile(executor._executable):
                    obj._executable = executor._executable
                    obj._dir = executor._dir
                    return obj

        obj.create_files(*args, **kwargs)
        obj.compile()
        if is_cached:
            cls.compiled_binary_cache[cache_key] = obj
        return obj

class CompiledExecutor(BaseExecutor, metaclass=_CompiledExecutorMeta):
    executable_size = env.compiler_size_limit * 1024
    compiler_time_limit = env.compiler_time_limit
    compile_output_index = 1

    is_cached = False
    warning: Optional[bytes] = None
    _executable: Optional[str] = None
    _code: Optional[str] = None

    def __init__(self, problem_id: str, source_code: bytes, *args, **kwargs) -> None:
        super().__init__(problem_id, source_code, **kwargs)
        self.warning = None
        self._executable = None

    def cleanup(self) -> None:
        if not self.is_cached:
            super().cleanup()

    def create_files(self, problem_id: str, source_code: bytes, *args, **kwargs) -> None:
        self._code = self._file(self.source_filename_format.format(problem_id=problem_id, ext=self.ext))
        with open(self._code, 'wb') as fo:
            fo.write(utf8bytes(source_code))

    def get_compile_args(self) -> List[str]:
        raise NotImplementedError()

    def get_compile_env(self) -> Optional[Dict[str, str]]:
        return None

    def get_compile_popen_kwargs(self) -> Dict[str, Any]:
        return {}

    def create_compile_process(self, args: List[str]) -> subprocess.Popen:
        env = self.get_compile_env() or os.environ.copy()
        assert self._dir is not None
        env['TMPDIR'] = self._dir

        return subprocess.Popen(
            [utf8bytes(a) for a in args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=utf8bytes(self._dir),
        )

    def get_compile_output(self, process: subprocess.Popen) -> bytes:
        limit = env.compiler_output_character_limit
        try:
            output = safe_communicate(process, None, outlimit=limit, errlimit=limit)[self.compile_output_index]
        except OutputLimitExceeded:
            output = b'compiler output too long (> 64kb)'

        if self.is_failed_compile(process):
            if hasattr(process, 'is_tle') and process.is_tle:
                output = b'compiler timed out (> %d seconds)' % self.compiler_time_limit
            self.handle_compile_error(output)
        return output

    def get_compiled_file(self) -> str:
        return self._file(self.problem)

    def is_failed_compile(self, process: subprocess.Popen) -> bool:
        return process.returncode != 0

    def handle_compile_error(self, output: bytes) -> None:
        raise CompileError(output)

    def get_binary_cache_key(self) -> bytes:
        return utf8bytes(self.problem) + self.source

    def compile(self) -> str:
        process = self.create_compile_process(self.get_compile_args())
        # Gắn thuộc tính is_tle để kiểm tra timeout
        process.is_tle = False
        try:
            process.communicate(timeout=self.compiler_time_limit)
        except subprocess.TimeoutExpired:
            process.is_tle = True
            process.kill()
        self.warning = self.get_compile_output(process)
        self._executable = self.get_compiled_file()
        return self._executable

    def get_cmdline(self, **kwargs) -> List[str]:
        return [self.problem]

    def get_executable(self) -> str:
        assert self._executable is not None
        return self._executable