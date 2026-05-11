import React, { useEffect, useState, useCallback } from "react";
import { ScrollView, View, Text, Pressable, Linking, RefreshControl, StyleSheet } from "react-native";
import { fetchToday } from "./api";
import type { Devotion } from "./types";
import CollapsibleText from "./components/CollapsibleText";

const colors = {
  bg: "#F5F7FB",
  card: "#FFFFFF",
  text: "#1E2330",
  dim: "#586077",
  primary: "#1F6BB5",
  primaryDark: "#0C2340",
  chipBg: "#E8ECF7",
};

const H2: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text style={{ fontSize: 18, fontWeight: "800", marginBottom: 8, color: colors.text }}>
    {children}
  </Text>
);

const Card: React.FC<{ title?: string; children: React.ReactNode }> = ({ title, children }) => (
  <View style={styles.card}>
    {title ? <H2>{title}</H2> : null}
    {children}
  </View>
);

export default function HomeScreen() {
  const [data, setData] = useState<Devotion | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchToday(); // make sure this points to dailylectio.org/devotions.json
      setData(d);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
    >
      <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 10, color: colors.text }}>
        {data?.date ?? "—"}
      </Text>

      {/* Quote */}
      {data?.quote ? (
        <Card title="Quote of the Day">
          <Text style={{ fontStyle: "italic", color: colors.text }}>{`“${data.quote}”`}</Text>
          {!!data.quoteCitation && (
            <Text style={{ marginTop: 6, color: colors.dim }}>— {data.quoteCitation}</Text>
          )}
        </Card>
      ) : null}

      {/* First Reading */}
      {data?.firstReading ? (
        <Card title={`First Reading${data.firstReadingRef ? ` (${data.firstReadingRef})` : ""}`}>
          <Text style={styles.body}>{data.firstReading}</Text>
        </Card>
      ) : null}

      {/* Psalm */}
      {data?.psalmSummary ? (
        <Card title={`Psalm${data.psalmRef ? ` (${data.psalmRef})` : ""}`}>
          <Text style={styles.body}>{data.psalmSummary}</Text>
        </Card>
      ) : null}

      {/* Second Reading (text only by your choice) */}
      {data?.secondReading ? (
        <Card title="Second Reading">
          <Text style={styles.body}>{data.secondReading}</Text>
        </Card>
      ) : null}

      {/* Gospel */}
      {data?.gospelSummary ? (
        <Card title={`Gospel${data.gospelRef ? ` (${data.gospelRef})` : ""}`}>
          <Text style={styles.body}>{data.gospelSummary}</Text>
        </Card>
      ) : null}

      {/* Saint */}
      {data?.saintReflection ? (
        <Card title="Saint of the Day">
          <Text style={styles.body}>{data.saintReflection}</Text>
        </Card>
      ) : null}

      {/* Prayer */}
      {data?.dailyPrayer ? (
        <Card title="Let Us Pray">
          <Text style={styles.body}>{data.dailyPrayer}</Text>
        </Card>
      ) : null}

      {/* Theological Synthesis (collapsible) */}
      {data?.theologicalSynthesis ? (
        <Card title="Theological Synthesis">
          <CollapsibleText numberOfLines={5}>{data.theologicalSynthesis}</CollapsibleText>
        </Card>
      ) : null}

      {/* Exegesis (collapsible) */}
      {data?.exegesis ? (
        <Card title="Exegesis">
          <CollapsibleText>{data.exegesis}</CollapsibleText>
        </Card>
      ) : null}

      {/* Buttons */}
      {(data?.usccbLink || true) && (
        <View style={styles.btnRow}>
          {!!data?.usccbLink && (
            <Pressable
              onPress={() => Linking.openURL(data.usccbLink!)}
              style={[styles.btn, { backgroundColor: colors.primary }]}
            >
              <Text style={styles.btnText}>USCCB Readings</Text>
            </Pressable>
          )}

          <Pressable
            onPress={() => Linking.openURL("https://www.lectiolinks.com")}
            style={[styles.btn, { backgroundColor: colors.primaryDark }]}
          >
            <Text style={styles.btnText}>Visit LectioLinks</Text>
          </Pressable>
        </View>
      )}

      {/* Optional tags chip */}
      {!!data?.tags?.length && (
        <View style={styles.tags}>
          <Text style={{ color: colors.primaryDark }}>
            Tags: {data.tags.join(", ")}
          </Text>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowRadius: 6,
    elevation: 1,
  },
  body: { fontSize: 16, lineHeight: 22, color: colors.text },
  btnRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 6, marginBottom: 12 },
  btn: { paddingVertical: 10, paddingHorizontal: 14, borderRadius: 10 },
  btnText: { color: "#fff", fontWeight: "800" },
  tags: { paddingVertical: 10, paddingHorizontal: 14, backgroundColor: colors.chipBg, borderRadius: 10 },
});
