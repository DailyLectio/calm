import React from "react";
import { View, Text, Image } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, spacing } from "../theme";

// Adjust the path below if your file lives elsewhere.
// From src/components → ../../assets/icon.png
const ICON = require("../../assets/icon.png");

export default function Header() {
  return (
    <LinearGradient
      colors={[colors.primary, "#14497E"]}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={{
        paddingTop: spacing(6),   // room for status bar
        paddingBottom: spacing(3),
        paddingHorizontal: spacing(2),
        borderBottomLeftRadius: 24,
        borderBottomRightRadius: 24
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <Image source={ICON} style={{ width: 36, height: 36, borderRadius: 8 }} />
        <View>
          <Text style={{ color: "#fff", fontSize: 20, fontWeight: "800" }}>FaithLinks</Text>
          <Text style={{ color: "rgba(255,255,255,0.9)" }}>Daily Lectio Devotions</Text>
        </View>
      </View>
    </LinearGradient>
  );
}
