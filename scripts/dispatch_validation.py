"""Dispatch read-only validation explicitly after a GITHUB_TOKEN publication."""
import os
import requests


def dispatch(token, repo, session=requests):
    response = session.post(f"https://api.github.com/repos/{repo}/actions/workflows/validate-publication.yml/dispatches",
                            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                            json={"ref": "main"}, timeout=20)
    response.raise_for_status()
    print("[ok] explicitly dispatched Validate Publication on current main")


if __name__ == "__main__":
    dispatch(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
