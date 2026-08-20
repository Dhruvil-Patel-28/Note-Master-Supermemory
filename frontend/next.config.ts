import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // The rewrite proxy kills requests after 30s by default; big uploads
    // (multi-MB docs) blow through that and return a bare 500.
    proxyTimeout: 600_000,
    // The proxy also truncates bodies >10MB by default, leaving the backend
    // hanging on a truncated multipart stream.
    proxyClientMaxBodySize: "100mb",
  },
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
