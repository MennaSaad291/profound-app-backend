import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "--tb=line", "-q"],
    capture_output=False
)
sys.exit(result.returncode)
