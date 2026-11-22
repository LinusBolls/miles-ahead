#!/usr/bin/env node
// Waits until a TestFlight build is processed (VALID), then adds it to the INTERNAL tester group.
// Never creates external groups or submits for beta review.
//
//   node tools/assign-testflight-build.mjs <buildNumber>
//
// Uses the ASC API key at ./asc-key.p8 (gitignored; never printed).
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_ID = process.env.ASC_APP_ID;
const INTERNAL_GROUP = "040b9f51-bd99-458d-a75f-9b81ac49de95";
const KEY_ID = process.env.ASC_KEY_ID;
const ISSUER = process.env.ASC_ISSUER_ID;
const key = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "asc-key.p8"), "utf8");

const buildNumber = process.argv[2];
if (!buildNumber) {
  console.error("usage: node tools/assign-testflight-build.mjs <buildNumber>");
  process.exit(2);
}

function token() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const data = `${b64({ alg: "ES256", kid: KEY_ID, typ: "JWT" })}.${b64({ iss: ISSUER, iat: now, exp: now + 1100, aud: "appstoreconnect-v1" })}`;
  return `${data}.${crypto.sign("sha256", Buffer.from(data), { key, dsaEncoding: "ieee-p1363" }).toString("base64url")}`;
}
async function asc(p, opts = {}) {
  const r = await fetch(`https://api.appstoreconnect.apple.com${p}`, {
    ...opts,
    headers: { authorization: `Bearer ${token()}`, "content-type": "application/json" },
  });
  const t = await r.text();
  if (!r.ok) throw new Error(`ASC ${r.status} ${p}: ${t.slice(0, 500)}`);
  return t ? JSON.parse(t) : {};
}

const deadline = Date.now() + 60 * 60_000;
let build;
for (;;) {
  const res = await asc(`/v1/builds?filter[app]=${APP_ID}&filter[version]=${buildNumber}&limit=5`);
  build = res.data?.[0];
  const state = build?.attributes?.processingState ?? "NOT_YET_UPLOADED";
  console.log(`${new Date().toLocaleTimeString()} build ${buildNumber}: ${state}${build ? ` (expired=${build.attributes.expired})` : ""}`);
  if (state === "VALID") break;
  if (state === "FAILED" || state === "INVALID") process.exit(1);
  if (Date.now() > deadline) process.exit(1);
  await new Promise((r) => setTimeout(r, 60_000));
}

await asc(`/v1/betaGroups/${INTERNAL_GROUP}/relationships/builds`, {
  method: "POST",
  body: JSON.stringify({ data: [{ type: "builds", id: build.id }] }),
});
const groups = await asc(`/v1/builds/${build.id}/betaGroups`).catch(() => ({ data: [] }));
console.log(
  `build ${buildNumber} (${build.id}) VALID; groups:`,
  (groups.data ?? []).map((g) => `${g.attributes.name}${g.attributes.isInternalGroup ? " (internal)" : ""}`).join(", ") || "(none listed)",
);
const detail = await asc(`/v1/builds/${build.id}/buildBetaDetail`).catch(() => null);
if (detail?.data) console.log("internalBuildState:", detail.data.attributes.internalBuildState);
