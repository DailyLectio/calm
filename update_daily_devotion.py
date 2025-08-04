#!/usr/bin/env python3
"""
Daily Devotion Update Script for FaithLinks
Extracts today's devotional from /public/weeklyfeed.json to /public/devotions.json
"""

import json
import os
import sys
from datetime import datetime
import logging

# Path setup (adjusted for your project structure)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
WEEKLY_PATH = os.path.join(PUBLIC_DIR, "weeklyfeed.json")
TARGET_PATH = os.path.join(PUBLIC_DIR, "devotions.json")
LOG_PATH = os.path.join(BASE_DIR, "devotion_update.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)

def update_daily_devotion():
    today = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Starting update for {today}")

    # Check if weeklyfeed.json exists in public/
    if not os.path.exists(WEEKLY_PATH):
        logging.error(f"{WEEKLY_PATH} not found")
        sys.exit(1)

    with open(WEEKLY_PATH, 'r', encoding='utf-8') as f:
        weekly_data = json.load(f)

    today_entry = next((e for e in weekly_data if e.get('date') == today), None)
    if not today_entry:
        logging.error(f"No entry for {today} in {WEEKLY_PATH}")
        sys.exit(1)

    with open(TARGET_PATH, 'w', encoding='utf-8') as f:
        json.dump([today_entry], f, indent=2, ensure_ascii=False)

    logging.info(f"✅ Wrote {TARGET_PATH} with 1 entry for {today}")

if __name__ == "__main__":
    update_daily_devotion()