import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Proxy API calls to the local FastAPI backend (localhost-only app).
    // Destination is localhost:8000 by design — if the deployment topology
    // ever changes, make this env-driven.
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
