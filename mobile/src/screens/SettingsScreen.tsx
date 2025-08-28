import React, { useEffect, useState } from "react";
import { View, Text, TextInput, Pressable, Alert } from "react-native";
import { getDailyTime, setDailyTime, getPremiumTimes, setPremiumTimes } from "../notifications";
import { useTheme } from "../theme";

const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;

export default function SettingsScreen() {
  const { colors } = useTheme();
  const [daily, setDaily] = useState("07:00");
  const [premium, setPremium] = useState<string[]>([]);
  const [newTime, setNewTime] = useState("");

  useEffect(() => { (async () => {
    setDaily(await getDailyTime());
    setPremium(await getPremiumTimes());
  })(); }, []);

  const saveDaily = async () => {
    if (!timeRegex.test(daily)) return Alert.alert("Invalid time", "Use 24-hour HH:MM");
    await setDailyTime(daily);
    Alert.alert("Saved", `Daily reminder set to ${daily}`);
  };

  const addPremiumTime = async () => {
    if (!timeRegex.test(newTime)) return Alert.alert("Invalid time", "Use 24-hour HH:MM");
    const next = Array.from(new Set([...premium, newTime])).sort();
    setPremium(next);
    await setPremiumTimes(next);
    setNewTime("");
  };

  const removePremiumTime = async (t: string) => {
    const next = premium.filter(x => x !== t);
    setPremium(next);
    await setPremiumTimes(next);
  };

  // Hook to your paywall: replace `isPremium` with your entitlement (RevenueCat or StoreKit/Billing)
  const isPremium = true; // placeholder during dev

  return (
    <View style={{ flex: 1, padding: 16, gap: 14 }}>
      <Text style={{ fontSize: 18, fontWeight: "800", color: colors.text }}>Standard daily notification</Text>
      <TextInput value={daily} onChangeText={setDaily} placeholder="HH:MM" autoCapitalize="none"
        style={{ borderWidth: 1, borderColor: "#ddd", padding: 12, borderRadius: 10, backgroundColor: "#fff", fontSize: 16 }} />
      <Pressable onPress={saveDaily} style={{ backgroundColor: colors.primary, padding: 12, borderRadius: 12 }}>
        <Text style={{ color: "#fff", fontWeight: "700", textAlign: "center" }}>Save Daily Time</Text>
      </Pressable>

      <View style={{ height: 10 }} />

      <Text style={{ fontSize: 18, fontWeight: "800", color: colors.text }}>Premium prayer reminders</Text>
      {!isPremium && <Text>Upgrade to Premium to set multiple prayer times.</Text>}

      {isPremium && (
        <>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput value={newTime} onChangeText={setNewTime} placeholder="HH:MM"
              style={{ flex: 1, borderWidth: 1, borderColor: "#ddd", padding: 12, borderRadius: 10, backgroundColor: "#fff", fontSize: 16 }} />
            <Pressable onPress={addPremiumTime} style={{ backgroundColor: colors.accent, padding: 12, borderRadius: 12, alignSelf: "stretch", justifyContent: "center" }}>
              <Text style={{ fontWeight: "800" }}>Add</Text>
            </Pressable>
          </View>

          <View style={{ gap: 8, marginTop: 8 }}>
            {premium.map(t => (
              <View key={t} style={{ flexDirection: "row", justifyContent: "space-between", backgroundColor: "#fff", padding: 12, borderRadius: 10 }}>
                <Text style={{ fontSize: 16 }}>{t}</Text>
                <Pressable onPress={() => removePremiumTime(t)}>
                  <Text style={{ color: "crimson", fontWeight: "700" }}>Remove</Text>
                </Pressable>
              </View>
            ))}
            {premium.length === 0 && <Text>No premium reminders set.</Text>}
          </View>
        </>
      )}
    </View>
  );
}