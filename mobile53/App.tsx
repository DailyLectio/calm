import { StatusBar } from "expo-status-bar";
import { Text, View, Pressable } from "react-native";
import * as Notifications from "expo-notifications";

export default function App() {
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 12 }}>
      <Text style={{ fontSize: 20, fontWeight: "700" }}>Lectio Links — SDK 53 smoke test</Text>
      <Pressable
        onPress={() => Notifications.getPermissionsAsync().then(console.log)}
        style={{ paddingHorizontal: 16, paddingVertical: 10, backgroundColor: "#1F6BB5", borderRadius: 10 }}
      >
        <Text style={{ color: "#fff", fontWeight: "800" }}>Check Notification Perms</Text>
      </Pressable>
      <StatusBar style="auto" />
    </View>
  );
}