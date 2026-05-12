from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser import generate_output


def available_cases():
    case_root = Path(__file__).resolve().parent / "cases"
    return sorted(path for path in case_root.iterdir() if path.is_dir())


def run_case(case_dir):
    input_text = (case_dir / "input.txt").read_text(encoding="utf-8")
    output_text = generate_output(input_text)

    test_dir = Path(__file__).resolve().parent
    shutil.copyfile(case_dir / "input.txt", test_dir / "input.txt")
    (test_dir / "output.txt").write_text(output_text, encoding="utf-8")

    print("=" * 70)
    print("CASE:", case_dir.name)
    readme = case_dir / "README.txt"
    if readme.exists():
        print(readme.read_text(encoding="utf-8").strip())
    print("-" * 70)
    print("output.txt:")
    print(output_text, end="" if output_text.endswith("\n") else "\n")
    print("=" * 70)


def main():
    cases = available_cases()
    if len(sys.argv) == 1:
        print("可用测试用例：")
        for index, case_dir in enumerate(cases, 1):
            print("%d. %s" % (index, case_dir.name))
        print("")
        print("运行单个用例：python -B test\\run_case.py 1")
        print("运行全部用例：python -B test\\run_case.py all")
        return 0

    arg = sys.argv[1].lower()
    if arg == "all":
        for case_dir in cases:
            run_case(case_dir)
        return 0

    try:
        index = int(arg)
    except ValueError:
        print("参数必须是编号或 all")
        return 1

    if index < 1 or index > len(cases):
        print("编号超出范围")
        return 1

    run_case(cases[index - 1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
