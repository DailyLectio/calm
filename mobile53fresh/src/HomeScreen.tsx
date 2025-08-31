import React, { useEffect, useState } from "react";
import { ScrollView, View, Text, Pressable, Linking, RefreshControl } from "react-native";
import { fetchToday } from "./api";
import type { Devotion } from "./types";

const H2: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text style={{ fontSize: 18, fontWeight: "800", marginTop: 18, marginBottom: 8 }}>
    {children}
  </Text>
);

const Card: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <View style={{ backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 12, shadowColor: "#000", shadowOpacity: 0.05, shadowRadius: 6, elevation: 1 }}>
    {children}
  </View>
);

const DebugBar = ({ data, onRefresh }: { data: Devotion | null; onRefresh: () => void }) => {
  const keys = data ? Object.keys(data) : [];
  return (
    <View style={{ backgroundColor: "#eef3ff", padding: 10, borderRadius: 8, marginBottom: 12 }}>
      <Text style={{ fontWeight: "700" }}>Debug</Text>
      <Text>Picked date: {data?.date ?? "—"}</Text>
      <Text numberOfLines={2} ellipsizeMode="tail">Keys: {keys.join(", ") || "—"}</Text>
      <Pressable onPress={onRefresh} style={{ marginTop: 6, padding: 8, backgroundColor: "#1F6BB5", borderRadius: 6 }}>
        <Text style={{ color: "#fff", fontWeight: "700" }}>Refresh (cache-bust)</Text>
      </Pressable>
    </View>
  );
};

export default function HomeScreen() {
  const [data, setData] = useState<Devotion | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const d = await fetchToday();
      setData(d);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: "#f7f7f7" }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
    >
      <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 6 }}>
        {data?.date ?? "—"}
      </Text>

      <DebugBar data={data} onRefresh={load} />

      {data?.quote && (
        <Card>
          <H2>Quote of the Day</H2>
          <Text style={{ fontStyle: "italic" }}>{`“${data.quote}”`}</Text>
          {!!data.quoteCitation && (
            <Text style={{ marginTop: 6, color: "#555" }}>— {data.quoteCitation}</Text>
          )}
        </Card>
      )}

      {data?.firstReading && (
        <Card>
          <H2>First Reading {data.firstReadingRef ? `(${data.firstReadingRef})` : ""}</H2>
          <Text>{data.firstReading}</Text>
        </Card>
      )}

      {data?.psalmSummary && (
        <Card>
          <H2>Psalm {data.psalmRef ? `(${data.psalmRef})` : ""}</H2>
          <Text>{data.psalmSummary}</Text>
        </Card>
      )}

{data?.secondReading && (
  <Card>
    <H2>Second Reading</H2>
    <Text>{data.secondReading}</Text>
  </Card>
)}

      {data?.gospelSummary && (
        <Card>
          <H2>Gospel {data.gospelRef ? `(${data.gospelRef})` : ""}</H2>
          <Text>{data.gospelSummary}</Text>
        </Card>
      )}

      {data?.saintReflection && (
        <Card>
          <H2>Saint of the Day</H2>
          <Text>{data.saintReflection}</Text>
        </Card>
      )}

      {data?.dailyPrayer && (
        <Card>
          <H2>Let Us Pray</H2>
          <Text>{data.dailyPrayer}</Text>
        </Card>
      )}

      {data?.theologicalSynthesis && (
        <Card>
          <H2>Theological Synthesis</H2>
          <Text>{data.theologicalSynthesis}</Text>
        </Card>
      )}

      {data?.exegesis && (
        <Card>
          <H2>Exegesis</H2>
          <Text>{data.exegesis}</Text>
        </Card>
      )}

      {(data?.usccbLink || data?.tags?.length) && (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 6 }}>
          {!!data.usccbLink && (
            <Pressable
              onPress={() => Linking.openURL(data.usccbLink!)}
              style={{ paddingVertical: 10, paddingHorizontal: 14, backgroundColor: "#1F6BB5", borderRadius: 10 }}
            >
              <Text style={{ color: "#fff", fontWeight: "700" }}>USCCB Readings</Text>
            </Pressable>
          )}
          {!!data.tags?.length && (
            <View style={{ paddingVertical: 10, paddingHorizontal: 14, backgroundColor: "#e8ecf7", borderRadius: 10 }}>
              <Text style={{ color: "#0c2340" }}>Tags: {data.tags.join(", ")}</Text>
            </View>
          )}
        </View>
      )}
    </ScrollView>
  );
}