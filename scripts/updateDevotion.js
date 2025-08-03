const fs = require('fs');

// Read the weekly feed
const weeklyFeed = JSON.parse(fs.readFileSync('public/weeklyfeed.json', 'utf8'));

// Get today's UTC date (adjust to local if needed)
const now = new Date();
const year = now.getUTCFullYear();
const month = String(now.getUTCMonth() + 1).padStart(2, "0");
const day = String(now.getUTCDate()).padStart(2, "0");
const todayString = `${year}-${month}-${day}`;

// Find today's entry
const todaysEntry = weeklyFeed.find(entry => entry.date === todayString);

if (todaysEntry) {
  fs.writeFileSync('public/devotions.json', JSON.stringify([todaysEntry], null, 2));
  console.log("Updated devotions.json for today:", todayString);
} else {
  // If not found, keep devotions.json empty or with a warning
  fs.writeFileSync('public/devotions.json', JSON.stringify([], null, 2));
  console.log("No entry found for today:", todayString, "- devotions.json emptied.");
}
