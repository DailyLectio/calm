#!/usr/bin/env python3
"""
Daily Devotion Update Script for FaithLinks
Updates today's devotional entry from weeklyfeed.json to:
- public/devotions.json (live source)
- dist/devotions.json (backup/build dist folder)
"""

import json
import os
import sys
from datetime import datetime
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DIST_DIR = os.path.join(BASE_DIR, "dist")

WEEKLY_PATH = os.path.join(PUBLIC_DIR, "weeklyfeed.json")
PUBLIC_TARGET_PATH = os.path.join(PUBLIC_DIR, "devotions.json")
DIST_TARGET_PATH = os.path.join(DIST_DIR, "devotions.json")
LOG_PATH = os.path.join(BASE_DIR, "devotion_update.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)

def update_devotions():
    today = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Starting daily devotion update for {today}")

    # Verify source data file exists
    if not os.path.exists(WEEKLY_PATH):
        logging.error(f"Source file missing: {WEEKLY_PATH}")
        sys.exit(1)

    try:
        with open(WEEKLY_PATH, "r", encoding="utf-8") as f:
            weekly_data = json.load(f)
    except Exception as e:
        logging.error(f"Error reading weeklyfeed.json: {e}")
        sys.exit(1)

    today_entry = next((entry for entry in weekly_data if entry.get("date") == today), None)
    if not today_entry:
        logging.error(f"No entry with date {today} found in weeklyfeed.json")
        sys.exit(1)

    # Write to public/devotions.json (live)
    try:
        with open(PUBLIC_TARGET_PATH, "w", encoding="utf-8") as f:
            json.dump([today_entry], f, indent=2, ensure_ascii=False)
        logging.info(f"✅ Updated {PUBLIC_TARGET_PATH} with entry for {today}")
    except Exception as e:
        logging.error(f"Failed writing to {PUBLIC_TARGET_PATH}: {e}")

    # Write to dist/devotions.json (backup)
    try:
        os.makedirs(DIST_DIR, exist_ok=True)  # Ensure dist folder exists
        with open(DIST_TARGET_PATH, "w", encoding="utf-8") as f:
            json.dump([today_entry], f, indent=2, ensure_ascii=False)
        logging.info(f"✅ Updated {DIST_TARGET_PATH} with entry for {today}")
    except Exception as e:
        logging.error(f"Failed writing to {DIST_TARGET_PATH}: {e}")

if __name__ == "__main__":
    update_devotions()