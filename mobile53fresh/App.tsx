import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, RefreshControl, View, Text, Pressable, Linking } from "react-native";
import { StatusBar } from "expo-status-bar";

type FeedItem = {
  date: string;
  quote?: string;
  quoteCitation?: string;
  firstReading?: string;
  psalmSummary?: string;
  gospelSummary?: string;
  saintReflection?: string;
  dailyPrayer?: string;
  theologicalSynthesis?: string;
  exegesis?: string;
  usccbLink?: string;
  firstReadingRef?: string;
  psalmRef?: string;
  gospelRef?: string;
  secondReading?: string;
  secondReadingRef?: string;
};

const FEED_URL = "https://dailylectio.org/devotions.json";

function Section({ title, children }: { title: string; children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <View style={{ marginTop: 16 }}>
      <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 6 }}>{title}</Text>
      {typeof children === "string" ? <Text style={{ lineHeight: 22 }}>{children}</Text> : children}
    </View>
  );
}

export default function App() {
  const [item, setItem] = useState<FeedItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(FEED_URL, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const first: FeedItem | undefined = Array.isArray(data) ? data[0] : data;
      if (!first) throw new Error("Empty feed response");
      setItem(first);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: "#fff" }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
    >
      <StatusBar style="dark" />
      <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 12 }}>
        {item?.date ?? "Loading…"}
      </Text>

      {err ? <Text style={{ color: "crimson", marginBottom: 12 }}>Problem loading feed: {err}</Text> : null}

      {item?.quote ? (
        <Section title="Quote of the Day">
          <Text style={{ fontStyle: "italic" }}>{`“${item.quote}”`}</Text>
          {item.quoteCitation ? <Text style={{ marginTop: 6 }}>— {item.quoteCitation}</Text> : null}
        </Section>
      ) : null}

      {item?.firstReading ? <Section title="First Reading">{item.firstReading}</Section> : null}
      {item?.psalmSummary ? <Section title="Psalm">{item.psalmSummary}</Section> : null}
      {item?.gospelSummary ? <Section title="Gospel">{item.gospelSummary}</Section> : null}
      {item?.saintReflection ? <Section title="Saint of the Day">{item.saintReflection}</Section> : null}
      {item?.dailyPrayer ? <Section title="Let Us Pray">{item.dailyPrayer}</Section> : null}
      {item?.theologicalSynthesis ? <Section title="Deep Dive">{item.theologicalSynthesis}</Section> : null}
      {item?.exegesis ? <Section title="Exegesis">{item.exegesis}</Section> : null}

      <View style={{ flexDirection: "row", gap: 12, marginTop: 20 }}>
        {item?.usccbLink ? (
          <Pressable
            onPress={() => Linking.openURL(item.usccbLink!)}
            style={{ paddingVertical: 12, paddingHorizontal: 14, borderRadius: 10, backgroundColor: "#1F6BB5" }}
          >
            <Text style={{ color: "#fff", fontWeight: "700" }}>Open USCCB Readings</Text>
          </Pressable>
        ) : null}

        <Pressable
          onPress={() => Linking.openURL("https://www.lectiolinks.com")}
          style={{ paddingVertical: 12, paddingHorizontal: 14, borderRadius: 10, backgroundColor: "#0C2340" }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>Visit LectioLinks</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}