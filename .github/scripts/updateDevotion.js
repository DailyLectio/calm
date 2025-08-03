const fs = require('fs');
const { DateTime } = require('luxon');

// Read the weekly feed
const weeklyFeed = JSON.parse(fs.readFileSync('public/weeklyfeed.json', 'utf8'));

// Get today's date in US Eastern Time (EST/EDT automatically handled)
const now = DateTime.now().setZone('America/New_York');
const year = now.year;
const month = String(now.month).padStart(2, "0");
const day = String(now.day).padStart(2, "0");
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