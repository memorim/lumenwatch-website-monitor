import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { webcrypto } from "node:crypto";
function browser() {
  let offset = 0;
  class Clock extends Date {
    static now() {
      return Date.now() + offset;
    }
  }
  let network = 0;
  const scope = {
    DEMO_SEED: JSON.parse(
      readFileSync(new URL("./seed.json", import.meta.url), "utf8"),
    ),
    structuredClone,
    Response,
    Headers,
    URL,
    DOMException,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    Date: Clock,
    crypto: webcrypto,
    location: new URL("https://example.test/project/"),
    fetch: async () => {
      network++;
      throw Error("Unexpected network request");
    },
  };
  runInNewContext(
    readFileSync(new URL("./browser.js", import.meta.url), "utf8"),
    scope,
  );
  return {
    call: async (path, method = "GET", body, headers) => {
      const response = await scope.fetch(path, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {}),
        headers,
      });
      return { status: response.status, body: await response.json() };
    },
    advance: (ms) => {
      offset += ms;
    },
    network: () => network,
  };
}
test("saved snapshots render, local targets do not start remote capture", async () => {
  const b = browser();
  assert((await b.call("/api/changes")).body.length > 0);
  const result = await b.call("/api/targets", "POST", {
    name: "Local target",
    url: "https://example.com/page",
    interval_minutes: 30,
  });
  assert.equal(result.status, 201);
  assert.equal(result.body.latest_snapshot, null);
  assert.equal(
    (await b.call("/api/targets/" + result.body.id + "/run", "POST")).status,
    409,
  );
  assert.equal(
    (
      await b.call("/api/targets", "POST", {
        name: "Unsafe link",
        url: "javascript:alert(1)",
      })
    ).status,
    400,
  );
  assert.equal(b.network(), 0);
});
