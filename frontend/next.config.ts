import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Separate build folder for the UI tests, so they can run while `npm run dev` is also running.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Docker builds set NEXT_OUTPUT=standalone for a small self-contained server.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Same-origin proxy to the FastAPI backend so the httpOnly session cookie just works.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
