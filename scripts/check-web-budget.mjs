#!/usr/bin/env node
// Enforce the first-load JavaScript budget from the v0.1.1 plan.
//
// Only scripts and modulepreload links referenced by dist/index.html count as
// first load; lazy route chunks are intentionally excluded.
import { gzipSync } from "node:zlib";
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, join } from "node:path";

const candidates = [
  join(process.cwd(), "web", "dist"),
  join(process.cwd(), "dist"),
];
const dist = candidates.find((path) => existsSync(join(path, "index.html")));
if (!dist) {
  console.error("web/dist/index.html not found; build the frontend first");
  process.exit(1);
}
const html = readFileSync(join(dist, "index.html"), "utf8");
const files = new Set();
for (const match of html.matchAll(/(?:src|href)="\/assets\/([^"?]+\.js)"/g)) {
  files.add(match[1]);
}
if (!files.size) {
  console.error("no first-load scripts found in index.html");
  process.exit(1);
}
const budget = 300 * 1024;
let total = 0;
const rows = [];
for (const name of files) {
  const path = join(dist, "assets", basename(name));
  const raw = readFileSync(path);
  const gzip = gzipSync(raw, { level: 9 }).length;
  total += gzip;
  rows.push([basename(name), statSync(path).size, gzip]);
}
rows.sort((a, b) => b[2] - a[2]);
for (const [name, raw, gzip] of rows) {
  console.log(`${name}: ${(raw / 1024).toFixed(1)} KiB raw, ${(gzip / 1024).toFixed(1)} KiB gzip`);
}
console.log(`first-load JS (gzip): ${(total / 1024).toFixed(1)} KiB / ${(budget / 1024).toFixed(0)} KiB`);
if (total > budget) {
  console.error("first-load JavaScript budget exceeded");
  process.exit(1);
}
