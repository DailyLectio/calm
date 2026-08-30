"""One assigned GitHub incident per failure; close on verified recovery. No feed writes."""
import argparse
import json
import os
from pathlib import Path
import requests
from scripts.check_live_publication import fingerprint

MARKER = "<!-- dailylectio-publication-health -->"
TITLE = "[Publication health] Action required"


class GitHub:
    def __init__(self):
        token = os.environ["GITHUB_TOKEN"]
        self.repo = os.environ.get("GITHUB_REPOSITORY", "DailyLectio/calm")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def call(self, method, path, payload=None):
        response = self.session.request(method, f"https://api.github.com/repos/{self.repo}/{path}",
                                        json=payload, timeout=20)
        response.raise_for_status()
        return response.json() if response.content else None


def report_health(api, report, run_url, assignee="DailyLectio", test=False):
    if test:
        api.call("GET", f"assignees/{assignee}")
        issue = api.call("POST", "issues", {"title": "[Publication health] Notification test",
            "body": f"Synthetic delivery test; not a production incident.\n\nRun: {run_url}\n\n"
                    "Assignment and closure test GitHub routing; email/push receipt requires account notification settings.",
            "assignees": [assignee]})
        api.call("PATCH", f"issues/{issue['number']}", {"state": "closed"})
        return issue["html_url"]
    issues, page = [], 1
    while True:
        batch = api.call("GET", f"issues?state=open&per_page=100&page={page}")
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    incident = next((i for i in issues if "pull_request" not in i and i.get("title") == TITLE
                     and i.get("user", {}).get("login") == "github-actions[bot]"
                     and MARKER in (i.get("body") or "")), None)
    if report["ok"]:
        if incident:
            api.call("POST", f"issues/{incident['number']}/comments", {"body": f"Publication verified healthy.\n\n{run_url}"})
            api.call("PATCH", f"issues/{incident['number']}", {"state": "closed"})
        return "healthy"
    error = report.get("error", "Health check failed before it could produce a report")
    signature = f"<!-- failure:{fingerprint(error)} -->"
    body = f"{MARKER}\n{signature}\nPublishing deadline: 06:00 America/New_York.\n\n{error}\n\nRun: {run_url}\n\nNo feed content was modified by this monitor."
    if incident:
        if signature not in (incident.get("body") or ""):
            api.call("POST", f"issues/{incident['number']}/comments", {"body": body})
            api.call("PATCH", f"issues/{incident['number']}", {"body": body})
        return incident["html_url"]
    api.call("GET", f"assignees/{assignee}")
    return api.call("POST", "issues", {"title": TITLE, "body": body, "assignees": [assignee]})["html_url"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("artifacts/publication-health.json"))
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {"ok": False}
    url = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    print(report_health(GitHub(), report, url, os.getenv("HEALTH_ASSIGNEE") or "DailyLectio",
                        os.getenv("ALERT_TEST") == "true"))
