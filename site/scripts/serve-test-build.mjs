import { preview } from "astro";

const server = await preview({ server: { host: "127.0.0.1", port: 41733 } });
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, async () => {
    await server.stop();
    process.exit(0);
  });
}
