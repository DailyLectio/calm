import React, { useEffect, useState, useMemo } from "react";
import { ScrollView, View, Text, Pressable, Linking, RefreshControl, StyleSheet } from "react-native";
import { colors, spacing, radius } from "./theme";
import Header from "./components/Header";
import { fetchToday } from "./api";
import type { Devotion } from "./types";

const Chip = ({ children }: { children: React.ReactNode }) => (
  <View style={styles.chip}>
    <Text style={styles.chipText}>{children}</Text>
  </View>
);

const Card: React.FC<{ children: React.ReactNode; title?: string; pill?: string }> = ({ children, title, pill }) => (
  <View style={styles.card}>
    <View style={styles.cardHeader}>
      <View style={styles.pill} />
      {title ? <Text style={styles.cardTitle}>{title}</Text> : null}
      {pill ? <Chip>{pill}</Chip> : null}
    </View>
    <View style={{ marginTop: spacing(1) }}>{children}</View>
  </View>
);

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

  // prefer actual secondReading; fall back to other shapes if present
  const secondReadingText = useMemo(() => {
    return (data as any)?.secondReading ?? (data as any)?.secondReadingSummary ?? (data as any)?.secondReadingRef ?? "";
  }, [data]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Header />
      <ScrollView
        contentContainerStyle={{ padding: spacing(2), paddingBottom: spacing(6) }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      >
        <Text style={styles.date}>{data?.date ?? "—"}</Text>

        {/* Quote */}
        {data?.quote ? (
          <Card title="Quote of the Day">
            <Text style={styles.quoteText}>{`“${data.quote}”`}</Text>
            {data?.quoteCitation ? <Text style={styles.citation}>— {data.quoteCitation}</Text> : null}
          </Card>
        ) : null}

        {/* First Reading */}
        {data?.firstReading ? (
          <Card title={`First Reading ${data?.firstReadingRef ? `(${data.firstReadingRef})` : ""}`}>
            <Text style={styles.body}>{data.firstReading}</Text>
          </Card>
        ) : null}

        {/* Psalm */}
        {data?.psalmSummary ? (
          <Card title={`Psalm ${data?.psalmRef ? `(${data.psalmRef})` : ""}`}>
            <Text style={styles.body}>{data.psalmSummary}</Text>
          </Card>
        ) : null}

        {/* Second Reading (text only, no citation header as requested) */}
        {secondReadingText ? (
          <Card title="Second Reading">
            <Text style={styles.body}>{secondReadingText}</Text>
          </Card>
        ) : null}

        {/* Gospel */}
        {data?.gospelSummary ? (
          <Card title={`Gospel ${data?.gospelRef ? `(${data.gospelRef})` : ""}`}>
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

        {/* Synthesis */}
        {data?.theologicalSynthesis ? (
          <Card title="Theological Synthesis">
            <Text style={styles.body}>{data.theologicalSynthesis}</Text>
          </Card>
        ) : null}

        {/* Exegesis */}
        {data?.exegesis ? (
          <Card title="Exegesis">
            <Text style={styles.body}>{data.exegesis}</Text>
          </Card>
        ) : null}

        {/* Links / Tags */}
        {(data?.usccbLink || data?.tags?.length) ? (
          <View style={{ flexDirection: "row", gap: spacing(1.5), flexWrap: "wrap", marginTop: spacing(1) }}>
            {!!data?.usccbLink && (
              <Pressable onPress={() => Linking.openURL(data.usccbLink!)} style={styles.ctaPrimary}>
                <Text style={styles.ctaPrimaryText}>USCCB Readings</Text>
              </Pressable>
            )}
            {!!data?.tags?.length && <Chip>Tags: {data.tags.join(", ")}</Chip>}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  date: {
    fontSize: 22,
    fontWeight: "800",
    color: colors.text,
    marginTop: spacing(2),
    marginBottom: spacing(1)
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius,
    padding: spacing(2),
    marginBottom: spacing(2),
    shadowColor: colors.shadow,
    shadowOpacity: 1,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
    borderWidth: 1,
    borderColor: colors.border
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing(1)
  },
  pill: {
    width: 6,
    height: 18,
    borderRadius: 3,
    backgroundColor: colors.accent
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: colors.text,
    flexShrink: 1
  },
  chip: {
    backgroundColor: "#EEF3FF",
    borderRadius: 999,
    paddingVertical: 4,
    paddingHorizontal: 10
  },
  chipText: {
    color: colors.primary,
    fontWeight: "700"
  },
  quoteText: {
    fontStyle: "italic",
    fontSize: 16,
    lineHeight: 22,
    color: colors.text
  },
  citation: {
    marginTop: 6,
    color: colors.subtext
  },
  body: {
    fontSize: 16,
    lineHeight: 22,
    color: colors.text
  },
  ctaPrimary: {
    paddingVertical: 10,
    paddingHorizontal: 14,
    backgroundColor: colors.primary,
    borderRadius: 10
  },
  ctaPrimaryText: {
    color: "#fff",
    fontWeight: "800"
  }
});
