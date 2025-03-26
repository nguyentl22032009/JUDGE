from dmoj.judge import Judge, Submission
from dmoj import executors

if __name__ == '__main__':
    # Load các executor
    executors.load_executors()

    # Danh sách submissions
    submissions = [
        Submission(
            id=1,
            problem_id="sum",
            language="CPP20",
            source="""
#include <iostream>
int main() {
    int a, b;
    std::cin >> a >> b;
    std::cout << a + b;
    return 0;
}
""",
            time_limit=2.0,  # 2 giây
            memory_limit=131072,  # 128mb
            short_circuit=True,
            meta={}
        )
    ]

    # Tạo judge instance
    judge = Judge()

    # Chấm từng submission và hiển thị kết quả
    for submission in submissions:
        print(f"Grading Submission #{submission.id} ({submission.problem_id})...")
        results = judge.begin_grading(submission)

        # Kiểm tra lỗi biên dịch hoặc thông báo
        has_compile_error = False
        for ipc_type, data in judge.current_judge_worker.communicate():
            if ipc_type == 'COMPILE-ERROR':
                print(f"Submission #{submission.id} Compile Error: {data[0].decode('utf-8')}")
                has_compile_error = True
                break
            elif ipc_type == 'COMPILE-MESSAGE':
                print(f"Submission #{submission.id} Compile Message: {data[0].decode('utf-8')}")

        # Nếu không có lỗi biên dịch, hiển thị kết quả
        if not has_compile_error and results:
            print(f"Submission #{submission.id} Results:")
            test_results = []
            for batch, case, result in results:
                verdict = result.readable_codes()[0]
                time_str = f"{result.execution_time:.3f}s"
                memory_str = f"{result.max_memory}kb"
                test_str = f"Test {case}: {verdict} [Time: {time_str}, Memory: {memory_str}]"
                if result.feedback:
                    test_str += f" (Feedback: {result.feedback})"
                test_results.append(test_str)
            print("  " + ", ".join(test_results))
        elif not has_compile_error and not results:
            print(f"Submission #{submission.id}: No results returned.")
        print()