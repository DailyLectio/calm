import json
import pathlib
import collections

# Adjust this path if your devotions.json is in a different folder
path = pathlib.Path("devotions.json")

# Read your existing JSON data
data = json.loads(path.read_text(encoding='utf-8'))

def fix(entry):
    # Rename reading_summary to first_reading
    if "reading_summary" in entry:
        entry["first_reading"] = entry.pop("reading_summary")
    # Insert a new "summary" field after "quote" if not present
    if "quote" in entry and "summary" not in entry:
        new = collections.OrderedDict()
        for k, v in entry.items():
            new[k] = v
            if k == "quote":
                new["summary"] = "This field will be a summary."
        entry.clear()
        entry.update(new)
    return entry

# Apply the fix to all entries
fixed_data = [fix(e) for e in data]

# Write the updated data back to the JSON file
path.write_text(json.dumps(fixed_data, indent=2, ensure_ascii=False), encoding='utf-8')

print("✓ devotions.json updated successfully.")