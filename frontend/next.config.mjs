/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === "development";
const backend = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: false,
  reactStrictMode: true,
  // Dev-only proxy so `next dev` (port 3000) talks to FastAPI on :8000.
  // Rewrites are ignored by static export; production is same-origin.
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }
    : {}),
};

export default nextConfig;
