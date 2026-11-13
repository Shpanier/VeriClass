import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes the dashboard into ../backend/web, which the server
// serves at "/" (so running a class needs no Node). `npm run dev` is for
// working on the dashboard: it proxies /api to a running server
// (VERICLASS_API, default http://127.0.0.1:8010).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/web",
    emptyOutDir: true,
  },
  server: {
    port: Number(process.env.VERICLASS_DASHBOARD_PORT || 5173),
    proxy: { "/api": process.env.VERICLASS_API || "http://127.0.0.1:8010" },
  },
});
