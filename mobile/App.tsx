// mobile/App.tsx
import React, { useEffect } from "react";
import { View, Text, Platform } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import HomeScreen from "./src/screens/HomeScreen";

const Stack = createNativeStackNavigator();

async function registerForPush() {
  // Ask the OS for permission (shows the system prompt)
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== "granted") return;

  // Android requires a channel to be created
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }

  // Get an Expo push token (works inside Expo Go)
  const projectId =
    (Constants.expoConfig as any)?.extra?.eas?.projectId ||
    (Constants.expoConfig as any)?.extra?.EAS_PROJECT_ID;

  const token = (
    await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined)
  ).data;

  // Send token to your backend
  const BACKEND_URL = (Constants.expoConfig as any)?.extra?.BACKEND_URL;
  if (BACKEND_URL) {
    await fetch(`${BACKEND_URL}/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    });
  }
}

// Tiny placeholder Settings screen to satisfy navigation
function SettingsScreen() {
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
      <Text>Settings (Reminders)</Text>
      <Text style={{ marginTop: 6, opacity: 0.7 }}>Premium scheduling UI goes here.</Text>
    </View>
  );
}

export default function App() {
  useEffect(() => {
    registerForPush();
  }, []);

  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Lectio Links" component={HomeScreen} />
        <Stack.Screen name="Settings" component={SettingsScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}