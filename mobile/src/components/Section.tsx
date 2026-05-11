import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useTheme } from "../theme";

export default function Section({ title, children }: { title: string; children?: React.ReactNode }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.wrap, { borderLeftColor: colors.accent }]}>
      <Text style={[styles.title, { color: colors.primary }]}>{title}</Text>
      {typeof children === "string" ? <Text style={[styles.body]}>{children}</Text> : children}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginVertical: 10, padding: 14, backgroundColor: "#fff", borderRadius: 14, borderLeftWidth: 4, shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 2 },
  title: { fontSize: 16, fontWeight: "700", marginBottom: 6 },
  body: { fontSize: 15, lineHeight: 22 }
});