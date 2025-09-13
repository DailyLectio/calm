import React from "react";
import { View, Text, Image, StyleSheet, Platform } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Constants from "expo-constants";
import { colors, spacing } from "../theme";

export default function Header() {
  const statusInset = Platform.select({ ios: 16, android: Constants.statusBarHeight || 0, default: 0 });

  return (
    <LinearGradient
      colors={["#1F6BB5", "#0C2340"]}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[styles.wrapper, { paddingTop: (statusInset ?? 0) + spacing(1.5) }]}
    >
      <View style={styles.row}>
        <Image
          source={require("../../assets/icon.png")}
          style={styles.logo}
          resizeMode="contain"
        />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>FaithLinks</Text>
          <Text style={styles.subtitle}>
            v{Constants.expoConfig?.version} · android {Constants.expoConfig?.android?.versionCode}
          </Text>
        </View>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: spacing(2),
    paddingBottom: spacing(1.5),
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "rgba(255,255,255,0.15)",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing(1.25),
  },
  logo: {
    width: 28,
    height: 28,
    borderRadius: 6,
    marginRight: spacing(0.5),
  },
  title: {
    color: "#fff",
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  subtitle: {
    color: "rgba(255,255,255,0.8)",
    fontSize: 12,
    marginTop: 2,
  },
});
