import React, { useState, useCallback } from "react";
import { Text, Pressable, View, StyleSheet, NativeSyntheticEvent, TextLayoutEventData } from "react-native";
import { colors, spacing } from "../theme";

type Props = {
  children: string;
  numberOfLines?: number; // default 6
};

export default function CollapsibleText({ children, numberOfLines = 6 }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);

  const onTextLayout = useCallback((e: NativeSyntheticEvent<TextLayoutEventData>) => {
    setTruncated(e.nativeEvent.lines.length > numberOfLines);
  }, [numberOfLines]);

  return (
    <View>
      <Text
        onTextLayout={onTextLayout}
        style={styles.body}
        numberOfLines={expanded ? undefined : numberOfLines}
      >
        {children}
      </Text>

      {truncated ? (
        <Pressable onPress={() => setExpanded(v => !v)} style={styles.moreBtn}>
          <Text style={styles.moreText}>{expanded ? "Show less" : "Read more"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  body: { fontSize: 16, lineHeight: 22, color: colors.text },
  moreBtn: { marginTop: spacing(1) },
  moreText: { color: colors.primary, fontWeight: "800" },
});
