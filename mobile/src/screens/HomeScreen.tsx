// mobile/src/screens/HomeScreen.tsx
import React, { useEffect, useState } from "react";
import { ScrollView, RefreshControl, View, Text, Linking, Pressable } from "react-native";
import { fetchToday } from "../api";
import { DailyFeed } from "../types";
import Section from "../components/Section";
import { useTheme } from "../theme";

export default function HomeScreen({ navigation }: any) {
  const [data, setData] = useState<DailyFeed | null>(null);
  const [loading, setLoading] = useState(false);
  const { colors } = useTheme();

  async function load() {
    setLoading(true);
    try {
      const d = await fetchToday();
      setData(d);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
    >
      <View style={{ padding: 16 }}>
        <Pressable onPress={() => navigation.navigate("Settings")} style={{ alignSelf: "flex-end", marginBottom: 8 }}>
          <Text style={{ color: colors.primary, fontWeight: "600" }}>Reminders ⚙️</Text>
        </Pressable>

        <Text style={{ fontSize: 22, fontWeight: "800", color: colors.text, marginBottom: 8 }}>
          {data?.date || "…"}
        </Text>

        {data?.quote && (
          <Section title="Quote of the Day">
            <Text style={{ fontStyle: "italic" }}>{`“${data.quote.text}”`}</Text>
            {data.quote.citation ? <Text style={{ marginTop: 6 }}>— {data.quote.citation}</Text> : null}
          </Section>
        )}

        {data?.firstReading && (
          <Section title={`First Reading ${data.firstReading.ref ? `(${data.firstReading.ref})` : ""}`}>
            {data.firstReading.summary || "—"}
          </Section>
        )}

        {data?.psalm && (
          <Section title={`Psalm ${data.psalm.ref ? `(${data.psalm.ref})` : ""}`}>
            {data.psalm.refrain ? `Refrain: ${data.psalm.refrain}\n\n` : ""}{data.psalm.summary || ""}
          </Section>
        )}

        {data?.gospel && (
          <Section title={`Gospel ${data.gospel.ref ? `(${data.gospel.ref})` : ""}`}>
            {data.gospel.summary || "—"}
          </Section>
        )}

        {data?.deepDive && <Section title="Deep Dive">{data.deepDive}</Section>}

        {data?.saint && (
          <Section title={`Saint of the Day${data.saint.name ? `: ${data.saint.name}` : ""}`}>
            {data.saint.bio || "—"}
          </Section>
        )}

        {data?.prayer && <Section title="Let Us Pray">{data.prayer}</Section>}

        <View style={{ height: 10 }} />

        <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
          {data?.readings_link && (
            <Pressable onPress={() => Linking.openURL(data.readings_link)} style={{ padding: 12, backgroundColor: colors.primary, borderRadius: 12 }}>
              <Text style={{ color: "#fff", fontWeight: "700" }}>Daily Scripture</Text>
            </Pressable>
          )}
          {data?.usccb_link && (
            <Pressable onPress={() => Linking.openURL(data.usccb_link)} style={{ padding: 12, backgroundColor: colors.accent, borderRadius: 12 }}>
              <Text style={{ color: "#000", fontWeight: "800" }}>USCCB Readings</Text>
            </Pressable>
          )}
        </View>
      </View>
    </ScrollView>
  );
}