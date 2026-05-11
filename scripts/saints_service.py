# scripts/saints_service.py
"""
No-op saints service to keep weekly generator running without any scraping.
All functions exist for compatibility but return empty results.
"""

from datetime import date

def fetch_litcal_api_saint(d: date):
    return "", {}

def fetch_usccb_saint(d: date):
    return "", {}

def fetch_vatican_saint(d: date):
    return "", {}

def fetch_catholicsaints_mobi(d: date):
    return "", {}

def get_saint_for_date(d: date):
    return "", {}

def normalize_saint_name(name: str) -> str:
    return (name or "").strip()

SAINT_SOURCE = "disabled"
