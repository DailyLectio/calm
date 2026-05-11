export type DailyFeed = {
  date: string;
  quote?: { text: string; citation?: string };
  firstReading?: { ref?: string; summary?: string };
  psalm?: { ref?: string; refrain?: string; summary?: string };
  gospel?: { ref?: string; summary?: string };
  deepDive?: string;
  saint?: { name?: string; bio?: string };
  prayer?: string;
  usccb_link?: string;
  readings_link?: string;
};