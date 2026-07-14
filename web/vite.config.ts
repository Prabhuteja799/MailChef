import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// build output is served directly by the FastAPI backend (see app/main.py) —
// same origin in production, so the app never needs CORS or a dev proxy there.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
