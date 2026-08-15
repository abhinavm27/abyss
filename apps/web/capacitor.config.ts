import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.curevoz.abyss",
  appName: "VELA",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
};

export default config;
