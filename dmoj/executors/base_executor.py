import errno
import os
import re
import shutil
import subprocess
import traceback
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

from dmoj.error import InternalError
from dmoj.judgeenv import env, skip_self_test
from dmoj.result import Result
from dmoj.utils.unicode import utf8bytes, utf8text

VersionFlags = Union[str, Tuple[str, ...]]
VersionTuple = Tuple[int, ...]
RuntimeVersion = Tuple[str, VersionTuple]
RuntimeVersionList = List[RuntimeVersion]

AutoConfigResult = Dict[str, Any]
AutoConfigOutput = Tuple[Optional[AutoConfigResult], bool, str, str]

version_cache: Dict[str, RuntimeVersionList] = {}

UTF8_LOCALE = 'C.UTF-8'

class ExecutorMeta(type):
    def __new__(mcs, name, bases, attrs) -> Any:
        if '__module__' in attrs:
            attrs['name'] = attrs['__module__'].split('.')[-1]
        return super().__new__(mcs, name, bases, attrs)

class BaseExecutor(metaclass=ExecutorMeta):
    ext: str
    nproc = 0
    command: Optional[str] = None
    command_paths: List[str] = []
    runtime_dict = env.runtime
    name: str
    test_program: str
    test_name = 'self_test'
    test_time = env.selftest_time_limit
    test_memory = env.selftest_memory_limit
    version_regex = re.compile(r'.*?(\d+(?:\.\d+)+)', re.DOTALL)
    source_filename_format = '{problem_id}.{ext}'

    _dir: Optional[str] = None

    def __init__(
        self,
        problem_id: str,
        source_code: bytes,
        dest_dir: Optional[str] = None,
        hints: Optional[List[str]] = None,
        unbuffered: bool = False,
        **kwargs,
    ) -> None:
        self._tempdir = dest_dir or env.tempdir
        self._dir = None
        self.problem = problem_id
        self.source = source_code
        self._hints = hints or []
        self.unbuffered = unbuffered

        for arg, value in kwargs.items():
            if not hasattr(self, arg):
                raise TypeError(f'Unexpected keyword argument: {arg}')
            setattr(self, arg, value)

    def cleanup(self) -> None:
        if not hasattr(self, '_dir'):
            print('BaseExecutor error: not initialized?')
            return
        if self._dir:
            try:
                shutil.rmtree(self._dir)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise

    def create_files(self, problem_id: str, source_code: bytes, *args, **kwargs) -> None:
        raise NotImplementedError()

    def __del__(self) -> None:
        self.cleanup()

    def _file(self, *paths: str) -> str:
        if self._dir is None:
            self._dir = tempfile.mkdtemp(dir=self._tempdir)
        return os.path.join(self._dir, *paths)

    @classmethod
    def get_executor_name(cls) -> str:
        return cls.__module__.split('.')[-1]

    def get_executable(self) -> Optional[str]:
        return None

    def get_cmdline(self, **kwargs) -> List[str]:
        raise NotImplementedError()

    def get_nproc(self) -> int:
        return self.nproc

    def populate_result(self, stderr: bytes, result: Result, process: subprocess.Popen) -> None:
        # Không có thông tin chi tiết như max_memory, context_switches từ cptbox, chỉ lấy thời gian và trạng thái cơ bản
        result.execution_time = process.execution_time if hasattr(process, 'execution_time') else 0.0
        result.max_memory = 0  # Không thể đo bộ nhớ chính xác mà không có cptbox
        result.wall_clock_time = 0  # Không đo wall time
        result.context_switches = (0, 0)  # Không đo context switches
        result.runtime_version = ', '.join(
            f'{runtime} {".".join(map(str, version))}' for runtime, version in self.get_runtime_versions()
        )

        # Xử lý trạng thái dựa trên returncode và timeout
        if process.returncode != 0:
            result.result_flag |= Result.RTE
        if hasattr(process, 'is_tle') and process.is_tle:
            result.result_flag |= Result.TLE

    def parse_feedback_from_stderr(self, stderr: bytes, process: subprocess.Popen) -> str:
        return ''

    def get_env(self) -> Dict[str, str]:
        env = {'LANG': UTF8_LOCALE}
        if self.unbuffered:
            env['PYTHONUNBUFFERED'] = '1'  # Chỉ áp dụng cho Python nếu cần, không dùng CPTBOX_STDOUT_BUFFER_SIZE
        return env

    def launch(self, *args, **kwargs) -> subprocess.Popen:
        assert self._dir is not None
        for src, dst in kwargs.get('symlinks', {}).items():
            src = os.path.abspath(os.path.join(self._dir, src))
            if os.path.commonprefix([src, self._dir]) == self._dir:
                if os.path.islink(src):
                    os.unlink(src)
                os.symlink(dst, src)
            else:
                raise InternalError('cannot symlink outside of submission directory')

        child_env = self.get_env()
        executable = self.get_executable()
        assert executable is not None
        cmdline = [utf8bytes(a) for a in self.get_cmdline(**kwargs) + list(args)]
        
        # Sử dụng subprocess.Popen thay vì TracedPopen
        process = subprocess.Popen(
            cmdline,
            executable=utf8bytes(executable),
            stdin=kwargs.get('stdin', subprocess.PIPE),
            stdout=kwargs.get('stdout', subprocess.PIPE),
            stderr=kwargs.get('stderr', subprocess.PIPE),
            env=child_env,
            cwd=utf8bytes(self._dir),
        )
        
            # Gắn thuộc tính is_tle nếu có timeout
        wall_time = kwargs.get('wall_time', kwargs.get('time', None))
        if wall_time:
            process.is_tle = False
            try:
                process.communicate(timeout=wall_time)
            except subprocess.TimeoutExpired:
                process.is_tle = True
                process.kill()
        return process

    @classmethod
    def get_command(cls) -> Optional[str]:
        return cls.runtime_dict.get(cls.command)

    @classmethod
    def initialize(cls) -> bool:
        command = cls.get_command()
        if command is None:
            return False
        if not os.path.isfile(command):
            return False
        return skip_self_test or cls.run_self_test()

    @classmethod
    def run_self_test(cls, output: bool = True, error_callback: Optional[Callable[[Any], Any]] = None) -> bool:
        if not cls.test_program:
            return True

        if output:
            print(f'Self-testing {cls.get_executor_name()}:'.ljust(39), end=' ')
        try:
            executor = cls(cls.test_name, utf8bytes(cls.test_program))
            proc = executor.launch(
                time=cls.test_time, memory=cls.test_memory, stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )

            test_message = b'echo: Hello, World!'
            stdout, stderr = proc.communicate(test_message + b'\n', timeout=cls.test_time)

            res = stdout.strip() == test_message and not stderr
            if output:
                cls.get_runtime_versions()
                usage = f'[{proc.execution_time:.3f}s, 0 KB]'  # Không đo được bộ nhớ
                print(f'{["Failed ", "Success"][res]} {usage:<19}', end=' ')
                print(', '.join(
                    [f'{runtime} {".".join(map(str, version))}' for runtime, version in cls.get_runtime_versions()]
                ))
            if stdout.strip() != test_message and error_callback:
                error_callback('Got unexpected stdout output:\n' + utf8text(stdout))
            if stderr and error_callback:
                error_callback('Got unexpected stderr output:\n' + utf8text(stderr))
            return res
        except Exception as e:
            if output:
                print('Failed')
                traceback.print_exc()
            if error_callback:
                error_callback(traceback.format_exc())
            return False

    @classmethod
    def get_versionable_commands(cls) -> List[Tuple[str, str]]:
        command = cls.get_command()
        assert cls.command is not None
        assert command is not None
        return [(cls.command, command)]

    @classmethod
    def get_runtime_versions(cls) -> RuntimeVersionList:
        key = cls.get_executor_name()
        if key in version_cache:
            return version_cache[key]

        versions: RuntimeVersionList = []
        for runtime, path in cls.get_versionable_commands():
            flags = cls.get_version_flags(runtime)
            version = None
            for flag in flags:
                try:
                    command = [path]
                    if isinstance(flag, (tuple, list)):
                        command.extend(flag)
                    else:
                        command.append(flag)
                    output = utf8text(subprocess.check_output(command, stderr=subprocess.STDOUT))
                except subprocess.CalledProcessError:
                    pass
                else:
                    version = cls.parse_version(runtime, output)
                    if version:
                        break
            versions.append((runtime, version or ()))
        version_cache[key] = versions
        return version_cache[key]

    @classmethod
    def parse_version(cls, command: str, output: str) -> Optional[VersionTuple]:
        match = cls.version_regex.match(output)
        if match:
            return tuple(map(int, match.group(1).split('.')))
        return None

    @classmethod
    def get_version_flags(cls, command: str) -> List[VersionFlags]:
        return ['--version']

    @classmethod
    def find_command_from_list(cls, files: List[str]) -> Optional[str]:
        for file in files:
            if os.path.isabs(file):
                if os.path.exists(file):
                    return file
            else:
                path = shutil.which(file)
                if path is not None:
                    return os.path.abspath(path)
        return None

    @classmethod
    def autoconfig_find_first(cls, mapping: Optional[Dict[str, List[str]]]) -> AutoConfigOutput:
        if mapping is None:
            return {}, False, 'Unimplemented', ''
        result = {}
        for key, files in mapping.items():
            file = cls.find_command_from_list(files)
            if file is None:
                return None, False, f'Failed to find "{key}"', ''
            result[key] = file
        return cls.autoconfig_run_test(result)

    @classmethod
    def autoconfig_run_test(cls, result: AutoConfigResult) -> AutoConfigOutput:
        executor: Any = type('Executor', (cls,), {'runtime_dict': result})
        executor.__module__ = cls.__module__
        errors: List[str] = []
        success = executor.run_self_test(output=False, error_callback=errors.append)
        if success:
            message = f'Using {list(result.values())[0]}' if len(result) == 1 else ''
        else:
            message = 'Failed self-test'
        return result, success, message, '\n'.join(errors)

    @classmethod
    def get_find_first_mapping(cls) -> Optional[Dict[str, List[str]]]:
        if cls.command is None:
            return None
        return {cls.command: cls.command_paths or [cls.command]}

    @classmethod
    def autoconfig(cls) -> AutoConfigOutput:
        return cls.autoconfig_find_first(cls.get_find_first_mapping())