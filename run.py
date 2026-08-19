import subprocess
import sys

print("Running email processing...\n")

result = subprocess.run(
    [sys.executable, "process.py"]
)

if result.returncode == 0:

    print("\nProcessing complete.")
    print("Starting Email Intelligence dashboard...\n")

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app_email.py"]
    )

else:

    print("\nEmail processing failed.")
    print("Streamlit dashboard will not be started.")