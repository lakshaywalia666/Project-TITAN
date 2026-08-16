import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Titan command center", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Titan Command Center · Cloud Launchpad<\/title>/i);
  assert.match(html, /Command center/);
  assert.match(html, /Create resource/);
  assert.match(html, /Autonomy boundary/);
  assert.match(html, /Security posture/);
  assert.match(html, /Launchpad/);
});

test("starter preview infrastructure is fully removed", async () => {
  const [page, commandCenter, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/command-center.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /CommandCenter/);
  assert.match(commandCenter, /Connect Titan APIs/);
  assert.match(commandCenter, /TITAN|Titan/);
  assert.match(commandCenter, /Launchpad/);
  assert.match(layout, /Titan Command Center/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
