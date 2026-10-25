import { fileURLToPath } from "node:url";

// Include the shared data/scenarios fixture outside the frontend directory.
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
export default {
  distDir: process.env.NEXT_DIST_DIR ?? '.next',
  turbopack: { root: repositoryRoot },
  outputFileTracingRoot: repositoryRoot,
  async rewrites() {
    const target = (process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};
