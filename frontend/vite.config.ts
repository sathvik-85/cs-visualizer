import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    // Disable compression so SSE events are not buffered by the dev proxy
    compress: false,
    proxy: {
      // SSE endpoint — must come before the generic /api rule
      "/api/stream": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Tell http-proxy not to buffer the response
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("accept-encoding", "identity");
          });
        },
      },
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
