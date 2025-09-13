import React from "react";
import { View, StatusBar } from "react-native";
import Header from "./src/components/Header";
import HomeScreen from "./src/HomeScreen";

export default function App() {
  return (
    <View style={{ flex: 1, backgroundColor: "#F5F7FB" }}>
      <StatusBar barStyle="light-content" />
      <Header />
      <HomeScreen />
    </View>
  );
}
