"""Read-only identity/permission check plus Git receive-pack dry run; no secret output."""
import os
import subprocess
import requests


def main():
    token = os.environ["PUBLISH_TOKEN"]
    repo = os.environ.get("GITHUB_REPOSITORY", "DailyLectio/calm")
    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        user = session.get("https://api.github.com/user", timeout=20)
        user.raise_for_status()
        repository = session.get(f"https://api.github.com/repos/{repo}", timeout=20)
        repository.raise_for_status()
        if not repository.json().get("permissions", {}).get("push"):
            raise ValueError("Publishing identity has no repository push permission")
        print(f"[ok] publishing identity: {user.json()['login']}; repository push permission confirmed")
    subprocess.run(["git", "push", "--dry-run", "origin", "HEAD:refs/heads/main"], check=True)
    print("[ok] Git publishing transport accepted dry run; production branch not modified")


if __name__ == "__main__":
    main()
