import { readFile, writeFile } from "node:fs/promises";

const names = ["retail_perishable", "retail_durable", "appointment_service"];
const entries = await Promise.all(names.map(async (name) => [name,
  JSON.parse(await readFile(new URL(`../../fixtures/${name}.json`, import.meta.url), "utf8"))]));
await writeFile(new URL("../src/generated/fixtures.json", import.meta.url),
  JSON.stringify(Object.fromEntries(entries), null, 2) + "\n");
