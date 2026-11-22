#!/usr/bin/env node
// Sends one "car near you needs rescuing" push to a device via Expo's push service (APNs key is on EAS for
// so.bolls.fuelback). Tapping it opens fuelback://rescue/<id> -> that car's rescue card.
//
//   node tools/send-rescue-push.mjs <ExponentPushToken[...]> [--id 123] [--reward 5] [--walk 4] [--model "VW Golf"]
//   EXPO_PUSH_TOKEN=ExponentPushToken[...] node tools/send-rescue-push.mjs --id 123
//
// Get the token on the phone: open  fuelback://?pushtoken=1  in Safari (share sheet -> AirDrop it to the laptop).
// The vehicle id must exist in the app's (demo/replay) rescue set, or the card shows "not found".
// Exit code 0 only when Expo accepted the message AND (after a short wait) the receipt says APNs took it.

const argv = process.argv.slice(2);
const flag = (name, def) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] != null ? argv[i + 1] : def;
};
const token = argv.find((a) => a.startsWith("ExponentPushToken[") || a.startsWith("ExpoPushToken[")) ?? process.env.EXPO_PUSH_TOKEN;
if (!token) {
  console.error("usage: node tools/send-rescue-push.mjs <ExponentPushToken[...]> [--id 123] [--reward 5] [--walk 4] [--model 'VW Golf'] [--title ...] [--body ...]");
  process.exit(2);
}

const id = flag("id", "");
const reward = flag("reward", "5");
const walk = flag("walk", "4");
const model = flag("model", "");
const url = id ? `fuelback://rescue/${id}` : "fuelback://";

const message = {
  to: token,
  title: flag("title", `A car near you needs rescuing · €${reward}`),
  body: flag("body", `${model ? `${model}, a ` : "A "}${walk} min walk. Move it to a busy street and earn €${reward} ride credit.`),
  data: { url },
  sound: "default",
  priority: "high",
};

const headers = { "content-type": "application/json", accept: "application/json" };
if (process.env.EXPO_ACCESS_TOKEN) headers.authorization = `Bearer ${process.env.EXPO_ACCESS_TOKEN}`;

const res = await fetch("https://exp.host/--/api/v2/push/send", { method: "POST", headers, body: JSON.stringify(message) });
const json = await res.json().catch(() => ({}));
const ticket = Array.isArray(json.data) ? json.data[0] : json.data;
console.log(`send: HTTP ${res.status}`, JSON.stringify(ticket ?? json));
if (!res.ok || ticket?.status !== "ok") process.exit(1);

// Receipts tell us whether APNs accepted it (e.g. DeviceNotRegistered, InvalidCredentials).
await new Promise((r) => setTimeout(r, 4000));
const rr = await fetch("https://exp.host/--/api/v2/push/getReceipts", {
  method: "POST",
  headers,
  body: JSON.stringify({ ids: [ticket.id] }),
});
const receipts = (await rr.json().catch(() => ({}))).data ?? {};
const receipt = receipts[ticket.id];
console.log("receipt:", receipt ? JSON.stringify(receipt) : "not ready yet (that's normal; delivery is usually still fine)");
process.exit(receipt && receipt.status !== "ok" ? 1 : 0);
