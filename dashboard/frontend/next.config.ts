import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "1";
const bePort = process.env.DASHBOARD_BE_PORT || "8100";

const nextConfig: NextConfig = {
  output: isExport ? "export" : "standalone",
  ...(!isExport && {
    async rewrites() {
      return [
        { source: "/api/:path*", destination: `http://127.0.0.1:${bePort}/api/:path*` },
        { source: "/ws/:path*", destination: `http://127.0.0.1:${bePort}/ws/:path*` },
        { source: "/healthz", destination: `http://127.0.0.1:${bePort}/healthz` },
      ];
    },
  }),
};

export default nextConfig;
