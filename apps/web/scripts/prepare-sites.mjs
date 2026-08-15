import { cp, mkdir, readdir, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const root = new URL("../", import.meta.url).pathname;
const dist = join(root, "dist");
const client = join(dist, "client");
const staging = join(root, ".sites-static");

await rm(staging, { recursive: true, force: true });
await mkdir(staging, { recursive: true });

for (const entry of await readdir(dist, { withFileTypes: true })) {
  if (entry.name === "server" || entry.name === "client") continue;
  await rename(join(dist, entry.name), join(staging, entry.name));
}

await rm(client, { recursive: true, force: true });
await mkdir(client, { recursive: true });
await cp(staging, client, { recursive: true });
await rm(staging, { recursive: true, force: true });
await mkdir(join(dist, "server"), { recursive: true });

await writeFile(
  join(dist, "server", "index.js"),
  `export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const response = await env.ASSETS.fetch(request);
    if (response.status !== 404 || url.pathname.includes('.')) return response;
    return env.ASSETS.fetch(new Request(new URL('/index.html', url), request));
  }
};\n`,
);
