import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import AsyncStorage from "@react-native-async-storage/async-storage";

const BACKEND_URL = Constants.expoConfig?.extra?.BACKEND_URL as string;
const DAILY_ID_KEY = "lectio.daily.notificationId";
const DAILY_TIME_KEY = "lectio.daily.hhmm"; // "07:00" local time

export async function registerForPushNotificationsAsync(): Promise<string | null> {
  if (!Device.isDevice) return null;

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") return null;

  const token = (await Notifications.getExpoPushTokenAsync({ projectId: Constants.expoConfig?.extra?.eas?.projectId })).data;

  // Send the token to your backend (used for remote pushes at the user’s preferred times)
  try {
    await fetch(`${BACKEND_URL}/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token })
    });
  } catch {}
  return token;
}

function parseHHMM(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  const now = new Date();
  const fire = new Date(now);
  fire.setHours(h, m, 0, 0);
  if (fire <= now) fire.setDate(fire.getDate() + 1);
  return fire;
}

export async function ensureDailyNotification() {
  const existingId = await AsyncStorage.getItem(DAILY_ID_KEY);
  if (existingId) {
    const scheduled = await Notifications.getAllScheduledNotificationsAsync();
    if (scheduled.some(s => (s.identifier || s.content?.data?.id) === existingId)) return;
  }
  await scheduleDailyAt(await getDailyTime());
}

export async function getDailyTime(): Promise<string> {
  const saved = await AsyncStorage.getItem(DAILY_TIME_KEY);
  return saved || "07:00";
}

export async function setDailyTime(hhmm: string) {
  await AsyncStorage.setItem(DAILY_TIME_KEY, hhmm);
  await rescheduleDaily(hhmm);
}

async function rescheduleDaily(hhmm: string) {
  const existingId = await AsyncStorage.getItem(DAILY_ID_KEY);
  if (existingId) await Notifications.cancelScheduledNotificationAsync(existingId);
  await scheduleDailyAt(hhmm);
}

async function scheduleDailyAt(hhmm: string) {
  const firstFire = parseHHMM(hhmm);
  const id = await Notifications.scheduleNotificationAsync({
    content: {
      title: "Today’s Lectio Link",
      body: "Tap to open today’s devotions.",
      data: { intent: "open_today" }
    },
    trigger: {
      hour: firstFire.getHours(),
      minute: firstFire.getMinutes(),
      repeats: true
    }
  });
  await AsyncStorage.setItem(DAILY_ID_KEY, id);
}

// Premium: allow multiple custom times
const PREMIUM_TIMES_KEY = "lectio.premium.times"; // JSON string array of "HH:MM"

export async function getPremiumTimes(): Promise<string[]> {
  const raw = await AsyncStorage.getItem(PREMIUM_TIMES_KEY);
  return raw ? JSON.parse(raw) : [];
}

export async function setPremiumTimes(times: string[]) {
  await AsyncStorage.setItem(PREMIUM_TIMES_KEY, JSON.stringify(times));
  // clear & reschedule all premium reminders
  const all = await Notifications.getAllScheduledNotificationsAsync();
  await Promise.all(
    all
      .filter(n => n.identifier?.startsWith?.("premium:"))
      .map(n => Notifications.cancelScheduledNotificationAsync(n.identifier as string))
  );
  for (const t of times) {
    const firstFire = parseHHMM(t);
    const id = await Notifications.scheduleNotificationAsync({
      content: { title: "Prayer Reminder", body: "Let’s pray.", data: { intent: "open_today" } },
      trigger: { hour: firstFire.getHours(), minute: firstFire.getMinutes(), repeats: true },
      identifier: `premium:${t}`
    } as any);
    // identifier is respected on Android; on iOS we fall back on best-effort; fine for lightweight app
  }
}