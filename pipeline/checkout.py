
import os
import re
import subprocess
from urllib.parse import urlparse

WORKSPACE = "/workspace"

def validate_repository(url):
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "github.com"
        and len(parts) == 2
        and all(
            re.fullmatch(r"[A-Za-z0-9-]+", part.removesuffix(".git"))
            for part in parts
        )
    )

def main():
    url = os.environ.get("REPOSITORY_URL", "").strip()
    branch = os.environ.get("REPOSITORY_BRANCH", "main").strip()

    if not validate_repository(url):
        raise SystemExit("Error: Set a valid HTTPS GitHub repository URL.")

    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise SystemExit("Error: Invalid branch name.")

    repo_name = urlparse(url).path.strip("/").split("/")[-1]
    repo_name = repo_name.removesuffix(".git")
    destination = os.path.join(WORKSPACE, repo_name)

    if os.path.exists(destination):
        raise SystemExit("Error: Repository directory already exists.")

    result = subprocess.run(
        [
            "git", "clone",
            "--depth", "1",
            "--single-branch",
            "--branch", branch,
            url,
            destination,
        ],
        check=False,
    )

    if result.returncode != 0:
        raise SystemExit("Repository checkout failed.")

    print(f"Checkout successful: {repo_name}")
    print(f"Branch: {branch}")

if __name__ == "__main__":
    main()
