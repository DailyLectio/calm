import Constants from "expo-constants";
import React, { createContext, useContext } from "react";

type Brand = { marianBlue: string; gold: string; black: string };
type Theme = { colors: { primary: string; accent: string; text: string; card: string; bg: string }; isDark: boolean };

const BrandContext = createContext<Theme | null>(null);

export const themeFromBrand = (): Theme => {
  const brand = (Constants.expoConfig?.extra?.BRAND || {}) as Brand;
  return {
    isDark: false,
    colors: {
      primary: brand.marianBlue || "#1F6BB5",
      accent: brand.gold || "#D4AF37",
      text: brand.black || "#000000",
      card: "#ffffff",
      bg: "#f7f7fb"
    }
  };
};

export const ThemeProvider = BrandContext.Provider;
export const useTheme = () => {
  const t = useContext(BrandContext);
  if (!t) throw new Error("Theme not provided");
  return t;
};