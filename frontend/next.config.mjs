import { fileURLToPath } from "node:url";

// Include the shared data/scenarios fixture outside the frontend directory.
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
export default {
  turbopack: { root: repositoryRoot },
  outputFileTracingRoot: repositoryRoot,
};
