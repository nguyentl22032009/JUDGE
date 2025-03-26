import glob
import os
from operator import itemgetter
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from dmoj.config import ConfigNode

problem_globs: List[str] = ['problem/*/']  # Đường dẫn mặc định tới problem/<id>

env: ConfigNode = ConfigNode(
    defaults={
        'selftest_time_limit': 10,  # 10 giây
        'selftest_memory_limit': 131072,  # 128mb RAM
        'generator_compiler_time_limit': 30,  # 30 giây
        'generator_time_limit': 20,  # 20 giây
        'generator_memory_limit': 524288,  # 512mb RAM
        'validator_compiler_time_limit': 30,  # 30 giây
        'validator_time_limit': 20,  # 20 giây
        'validator_memory_limit': 524288,  # 512mb RAM
        'compiler_time_limit': 10,  # 10 giây
        'compiler_size_limit': 131072,  # 128mb
        'compiler_output_character_limit': 65536,  # Giới hạn ký tự đầu ra biên dịch
        'compiled_binary_cache_dir': None,  # Thư mục cache mặc định
        'compiled_binary_cache_size': 100,  # Số lượng file thực thi tối đa trong cache
        'runtime': {},
        'extra_fs': {},
    },
    dynamic=False,
)

_root: str = os.path.dirname(__file__)

_problem_root_cache: Dict[str, str] = {}

def get_problem_root(problem_id) -> Optional[str]:
    cached_root = _problem_root_cache.get(problem_id)
    if cached_root is None or not os.path.isfile(os.path.join(cached_root, 'init.yml')):
        problem_root_dir = os.path.join('problem', problem_id)  # Đường dẫn cố định: problem/<id>
        problem_config = os.path.join(problem_root_dir, 'init.yml')
        if os.path.isfile(problem_config):
            _problem_root_cache[problem_id] = problem_root_dir
            return problem_root_dir
    return cached_root

_problem_dirs_cache: Optional[List[str]] = None

def get_problem_roots() -> List[str]:
    global _problem_dirs_cache
    if _problem_dirs_cache is not None:
        return _problem_dirs_cache
    dirs = []
    dirs_set = set()
    for dir_glob in problem_globs:
        config_glob = os.path.join(dir_glob, 'init.yml')
        root_dirs = {os.path.dirname(x) for x in glob.iglob(config_glob, recursive=True)}
        for root_dir in root_dirs:
            if root_dir not in dirs_set:
                dirs.append(root_dir)
                dirs_set.add(root_dir)
    _problem_dirs_cache = dirs
    return dirs

def clear_problem_dirs_cache() -> None:
    global _problem_dirs_cache
    _problem_dirs_cache = None

def get_supported_problems_and_mtimes() -> List[Tuple[str, float]]:
    problems = []
    problem_dirs: Dict[str, str] = {}
    for dir_glob in problem_globs:
        for problem_config in glob.iglob(os.path.join(dir_glob, 'init.yml'), recursive=True):
            if os.access(problem_config, os.R_OK):
                problem_dir = os.path.dirname(problem_config)
                problem = os.path.basename(problem_dir)
                if problem not in problem_dirs:
                    problem_dirs[problem] = problem_dir
                    problems.append((problem, os.path.getmtime(problem_dir)))
    return problems

def get_supported_problems() -> Iterable[str]:
    return map(itemgetter(0), get_supported_problems_and_mtimes())

def get_runtime_versions():
    from dmoj.executors import executors
    return {name: clazz.Executor.get_runtime_versions() for name, clazz in executors.items()}