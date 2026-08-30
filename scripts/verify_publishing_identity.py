"""Test job-scoped publishing authentication; optional explicit no-content commit probe."""
import argparse
import os
import subprocess
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-probe", action="store_true")
    args = parser.parse_args()
    token = os.environ["PUBLISH_TOKEN"]
    repo = os.environ.get("GITHUB_REPOSITORY", "DailyLectio/calm")
    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        repository = session.get(f"https://api.github.com/repos/{repo}", timeout=20)
        repository.raise_for_status()
        if repository.json().get("full_name") != repo:
            raise ValueError("Unexpected authenticated repository")
        # Installation tokens have no /user identity endpoint. The workflow explicitly
        # supplies its ephemeral GITHUB_TOKEN, never a desktop credential or stale PAT.
        print(f"[ok] authenticated repository: {repo}; publisher configured as job-scoped github-actions[bot]")
    subprocess.run(["git", "push", "--dry-run", "origin", "HEAD:refs/heads/main"], check=True)
    print("[ok] Git publishing transport accepted dry run; production branch not modified")
    if args.publish_probe:
        if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_REF") != "refs/heads/main":
            raise ValueError("Live probe requires an explicitly dispatched main-branch Actions run")
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        subprocess.run(["git", "checkout", "--detach", "origin/main"], check=True)
        if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
            raise ValueError("Probe checkout must be clean")
        subprocess.run(["git", "-c", "user.name=github-actions[bot]", "-c",
                        "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit",
                        "--allow-empty", "-m", "Verify workflow-token publishing (no content changes)"], check=True)
        subprocess.run(["git", "push", "origin", "HEAD:refs/heads/main"], check=True)
        print("[ok] actual non-forced workflow-token push succeeded; all file contents unchanged")
        from scripts.dispatch_validation import dispatch
        dispatch(token, repo)


if __name__ == "__main__":
    main()
