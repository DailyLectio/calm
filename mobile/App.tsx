import React, { useEffect, useMemo } from "react";
import { Platform, UIManager } from "react-native";
import { NavigationContainer, DefaultTheme, DarkTheme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import HomeScreen from "../app/src/screens/HomeScreen";
import SettingsScreen from "../app/src/screens/SettingsScreen";
import { registerForPushNotificationsAsync, ensureDailyNotification } from "./notifications";
import { ThemeProvider, themeFromBrand } from "../app/src/theme";
import * as Notifications from "expo-notifications";

const Stack = createNativeStackNavigator();

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: false
  })
});

// Enable LayoutAnimation on Android
if (Platform.OS === "android" && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

export default function App() {
  const theme = useMemo(() => themeFromBrand(), []);

  useEffect(() => {
    // Register for push & schedule the standard daily reminder
    (async () => {
      await registerForPushNotificationsAsync();
      await ensureDailyNotification(); // 7:00 AM local default (modifiable in Settings)
    })();
  }, []);

  return (
    <ThemeProvider value={theme}>
      <NavigationContainer theme={theme.isDark ? DarkTheme : DefaultTheme}>
        <Stack.Navigator>
          <Stack.Screen name="Home" component={HomeScreen} options={{ title: "Today’s Lectio Link" }} />
          <Stack.Screen name="Settings" component={SettingsScreen} options={{ title: "Prayer Reminders" }} />
        </Stack.Navigator>
      </NavigationContainer>
    </ThemeProvider>
  );
}