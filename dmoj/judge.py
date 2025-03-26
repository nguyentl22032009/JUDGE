import multiprocessing
import threading
from enum import Enum
from typing import Generator, List, NamedTuple, Optional, Tuple

from dmoj.error import CompileError
from dmoj.judgeenv import clear_problem_dirs_cache, env, get_supported_problems_and_mtimes
from dmoj.problem import BaseTestCase, BatchedTestCase, Problem, TestCase
from dmoj.result import Result
from dmoj.utils.unicode import utf8bytes

class IPC(Enum):
    HELLO = 'HELLO'
    BYE = 'BYE'
    COMPILE_ERROR = 'COMPILE-ERROR'
    COMPILE_MESSAGE = 'COMPILE-MESSAGE'
    RESULT = 'RESULT'
    BATCH_BEGIN = 'BATCH-BEGIN'
    BATCH_END = 'BATCH-END'
    GRADING_BEGIN = 'GRADING-BEGIN'
    GRADING_END = 'GRADING-END'
    GRADING_ABORTED = 'GRADING-ABORTED'
    UNHANDLED_EXCEPTION = 'UNHANDLED_EXCEPTION'
    REQUEST_ABORT = 'REQUEST-ABORT'

IPC_TIMEOUT = 60  # seconds

Submission = NamedTuple(
    'Submission',
    [
        ('id', int),
        ('problem_id', str),
        ('language', str),
        ('source', str),
        ('time_limit', float),
        ('memory_limit', int),
        ('short_circuit', bool),
        ('meta', dict),
    ],
)

class Judge:
    def __init__(self):
        self.current_judge_worker: Optional[JudgeWorker] = None
        self._grading_lock = threading.Lock()

    @property
    def current_submission(self):
        worker = self.current_judge_worker
        return worker.submission if worker else None

    def begin_grading(self, submission: Submission) -> list:
        self._grading_lock.acquire()
        assert self.current_judge_worker is None

        print(f"Start grading {submission.problem_id}/{submission.id} in {submission.language}...")
        self.current_judge_worker = JudgeWorker(submission)

        ipc_ready_signal = threading.Event()
        results = []
        grading_thread = threading.Thread(
            target=self._grading_thread_main, args=(ipc_ready_signal, results), daemon=True
        )
        grading_thread.start()
        ipc_ready_signal.wait()
        grading_thread.join()

        print(f"Done grading {submission.problem_id}/{submission.id}.\n")
        self.current_judge_worker = None
        self._grading_lock.release()
        return results

    def _grading_thread_main(self, ipc_ready_signal: threading.Event, results: list) -> None:
        assert self.current_judge_worker is not None

        ipc_handler_dispatch = {
            IPC.HELLO: lambda _r: ipc_ready_signal.set(),
            IPC.COMPILE_ERROR: lambda r, msg: print(f"Compile Error: {msg}"),
            IPC.COMPILE_MESSAGE: lambda r, msg: print(f"Compile Message: {msg}"),
            IPC.GRADING_BEGIN: lambda r, pretest: print(f"Grading {'pretests' if pretest else 'tests'}..."),
            IPC.GRADING_END: lambda r: print("Grading completed."),
            IPC.GRADING_ABORTED: lambda r: print("Grading aborted."),
            IPC.BATCH_BEGIN: lambda r, num: print(f"Batch #{num}"),
            IPC.BATCH_END: lambda r, num: None,
            IPC.RESULT: lambda r, batch, case, res: results.append((batch, case, res)),
            IPC.UNHANDLED_EXCEPTION: lambda r, msg: print(f"Error: {msg}"),
        }

        for ipc_type, data in self.current_judge_worker.communicate():
            handler_func = ipc_handler_dispatch.get(ipc_type)
            if handler_func:
                handler_func(None, *data)
            else:
                print(f"Unexpected IPC message: {ipc_type} {data}")

    def abort_grading(self):
        worker = self.current_judge_worker
        if worker:
            print(f"Aborting grading {worker.submission.id}...")
            worker.request_abort_grading()
            worker.wait_with_timeout()

class JudgeWorker:
    def __init__(self, submission: Submission) -> None:
        self.submission = submission
        self._abort_requested = False
        self._sent_sigkill_to_worker_process = False
        self.grader = None

        self.worker_process_conn, child_conn = multiprocessing.Pipe()
        self.worker_process = multiprocessing.Process(
            name=f"DMOJ Judge Handler for {submission.problem_id}/{submission.id}",
            target=self._worker_process_main,
            args=(child_conn, self.worker_process_conn),
        )
        self.worker_process.start()
        child_conn.close()

    def communicate(self) -> Generator[Tuple[IPC, tuple], None, None]:
        recv_timeout = max(60, int(2 * self.submission.time_limit))
        while True:
            if not self.worker_process_conn.poll(timeout=recv_timeout):
                print(f"Worker timeout after {recv_timeout}s, killing...")
                self.worker_process.kill()
                raise TimeoutError
            ipc_type, data = self.worker_process_conn.recv()
            if ipc_type == IPC.BYE:
                self.worker_process_conn.send((IPC.BYE, ()))
                return
            yield ipc_type, data

    def wait_with_timeout(self) -> None:
        if self.worker_process and self.worker_process.is_alive():
            self.worker_process.join(timeout=IPC_TIMEOUT)
            if self.worker_process.is_alive():
                print("Worker still alive, forcing kill...")
                self._sent_sigkill_to_worker_process = True
                self.worker_process.kill()

    def request_abort_grading(self) -> None:
        try:
            self.worker_process_conn.send((IPC.REQUEST_ABORT, ()))
        except Exception as e:
            print(f"Failed to send abort request: {e}")

    def _worker_process_main(self, judge_conn, worker_conn) -> None:
        worker_conn.close()
        judge_conn.send((IPC.HELLO, ()))

        def _ipc_recv_thread_main():
            while True:
                ipc_type, data = judge_conn.recv()
                if ipc_type == IPC.BYE:
                    return
                elif ipc_type == IPC.REQUEST_ABORT:
                    self._do_abort()

        ipc_recv_thread = threading.Thread(target=_ipc_recv_thread_main, daemon=True)
        ipc_recv_thread.start()

        try:
            for ipc_msg in self._grade_cases():
                judge_conn.send(ipc_msg)
            judge_conn.send((IPC.BYE, ()))
        except Exception as e:
            judge_conn.send((IPC.UNHANDLED_EXCEPTION, (str(e),)))
            judge_conn.send((IPC.BYE, ()))
        finally:
            ipc_recv_thread.join(timeout=IPC_TIMEOUT)

    def _grade_cases(self) -> Generator[Tuple[IPC, tuple], None, None]:
        problem = Problem(
            self.submission.problem_id, self.submission.time_limit, self.submission.memory_limit, self.submission.meta
        )

        try:
            self.grader = problem.grader_class(
                self, problem, self.submission.language, utf8bytes(self.submission.source)
            )
        except CompileError as compilation_error:
            yield IPC.COMPILE_ERROR, (compilation_error.message,)
            return
        else:
            warning = getattr(self.grader.binary, 'warning', None)
            if warning:
                yield IPC.COMPILE_MESSAGE, (warning,)

        yield IPC.GRADING_BEGIN, (problem.run_pretests_only,)

        flattened_cases: List[Tuple[Optional[int], BaseTestCase]] = []
        batch_number = 0
        for case in problem.cases():
            if isinstance(case, BatchedTestCase):
                batch_number += 1
                for batched_case in case.batched_cases:
                    flattened_cases.append((batch_number, batched_case))
            else:
                flattened_cases.append((None, case))

        case_number = 0
        is_short_circuiting = False
        for batch_number, case in flattened_cases:
            if batch_number:
                yield IPC.BATCH_BEGIN, (batch_number,)
            case_number += 1

            if is_short_circuiting:
                result = Result(case, result_flag=Result.SC)
            else:
                result = self.grader.grade(case)
                if self._abort_requested:
                    yield IPC.GRADING_ABORTED, ()
                    return
                if result.result_flag & Result.WA and self.submission.short_circuit:
                    is_short_circuiting = True

            result.proc_output = utf8bytes(result.output)
            yield IPC.RESULT, (batch_number, case_number, result)
            if batch_number:
                yield IPC.BATCH_END, (batch_number,)

        yield IPC.GRADING_END, ()

    def _do_abort(self) -> None:
        self._abort_requested = True
        if self.grader:
            self.grader.abort_grading()