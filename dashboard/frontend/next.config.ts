import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = {
  output: isExport ? "export" : "standalone",
  ...(!isExport && {
    async rewrites() {
      return [
        { source: "/api/:path*", destination: "http://127.0.0.1:8100/api/:path*" },
        { source: "/ws/:path*", destination: "http://127.0.0.1:8100/ws/:path*" },
        { source: "/healthz", destination: "http://127.0.0.1:8100/healthz" },
      ];
    },
  }),
};

export default nextConfig;
