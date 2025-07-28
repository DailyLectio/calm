import json
import pathlib
import collections

# Path to your devotions.json file, adjust if needed
json_path = pathlib.Path("devotions.json")

# Read existing data
with json_path.open(encoding='utf-8') as f:
    data = json.load(f)

def add_tags(entry):
    # Only add tag fields if they don't exist, so you can preserve any existing tags
    if 'cycle' not in entry:
        entry['cycle'] = "N/A"  # Placeholder, e.g., "A", "B", or "C"
    if 'weekday_cycle' not in entry:
        entry['weekday_cycle'] = "N/A"  # Placeholder, e.g., "I" or "II"
    if 'feast' not in entry:
        entry['feast'] = "None"  # Placeholder text
    if 'gospel_reference' not in entry:
        entry['gospel_reference'] = "Unknown"  # Placeholder text
    return entry

# Process all entries
updated_data = [add_tags(entry) for entry in data]

# Write updated data back to file with pretty printing
with json_path.open('w', encoding='utf-8') as f:
    json.dump(updated_data, f, indent=2, ensure_ascii=False)

print("✓ devotions.json updated with liturgical tags")
