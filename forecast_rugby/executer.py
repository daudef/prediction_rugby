import datetime
import subprocess
import sys
import pathlib

from forecast_rugby import main as main_module


def get_log_file_path(is_success: bool):
    now = datetime.datetime.now()
    log_file = (
        pathlib.Path(__file__).parent.parent
        / "logs"
        / now.strftime("%Y-%m-%d")
        / now.strftime(f"%H:%M:%S_{'ok' if is_success else 'err'}.log")
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return log_file


def main():
    process = subprocess.Popen(
        [sys.executable, main_module.__file__],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        process.wait(timeout=20)
        is_success = process.returncode == 0
    except:
        is_success = False
        raise
    finally:
        logs = None
        errors = None
        if process.stdout is not None:
            logs = process.stdout.read()
        if process.stderr is not None:
            errors = process.stderr.read()

        with get_log_file_path(is_success).open("w", encoding="utf-8") as f:
            f.writelines(["STDOUT\n", logs or "", "\nSTDERR\n", errors or ""])


if __name__ == "__main__":
    main()
