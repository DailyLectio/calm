// src/components/ReadMore.tsx
import React, { useState } from "react";
import { Text, Pressable } from "react-native";
import { colors } from "../theme";

export default function ReadMore({ text, min = 600 }: { text: string; min?: number }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;

  const showToggle = text.length > min;
  const visible = open || !showToggle ? text : text.slice(0, min) + "…";

  return (
    <>
      <Text style={{ color: colors.text, lineHeight: 22 }}>{visible}</Text>
      {showToggle && (
        <Pressable onPress={() => setOpen(!open)} style={{ marginTop: 8 }}>
          <Text style={{ color: colors.brand, fontWeight: "700" }}>{open ? "Show less ▲" : "Read more ▼"}</Text>
        </Pressable>
      )}
    </>
  );
}
