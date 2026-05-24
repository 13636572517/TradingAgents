import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { VitePWA } from "vite-plugin-pwa"

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "TradingAgents",
        short_name: "TradingAgents",
        description: "AI 多代理金融分析平台",
        theme_color: "#863bff",
        background_color: "#0f0f14",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
          { src: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        runtimeCaching: [
          {
            urlPattern: /^\/api\//,
            handler: "NetworkFirst",
            options: { cacheName: "api-cache", networkTimeoutSeconds: 10 },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8001",
    },
  },
})
