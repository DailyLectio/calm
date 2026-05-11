export type Devotion = {
  date: string;

  // core content
  quote?: string;
  quoteCitation?: string;

  firstReading?: string;         // summary text
  psalmSummary?: string;         // summary text
    // NEW – Sundays
  secondReading?: string;          // usually the citation on Sundays
  gospelSummary?: string;        // summary text

  saintReflection?: string;
  dailyPrayer?: string;
  theologicalSynthesis?: string; // long-form
  exegesis?: string;             // long-form

  // references / links
  secondReading?: string;
  usccbLink?: string;
  cycle?: string;
  weekdayCycle?: string;
  feast?: string | null;
  gospelReference?: string;
  firstReadingRef?: string;
  secondReadingRef?: string;
  psalmRef?: string;
  gospelRef?: string;
  lectionaryKey?: string;

  // optional
  tags?: string[];
};