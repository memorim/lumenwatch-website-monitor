// Browser-only adapter, loaded exclusively by scripts/build_demo.py.
// ponytail: state lasts for one page session; use the documented server for shared, durable data.
(() => {
  const state = structuredClone(globalThis.DEMO_SEED);
  const fail = (message, status = 400) => {
    throw Object.assign(new Error(message), { status });
  };
  const text = (value, min = 1, max = 200) => {
    if (
      typeof value !== "string" ||
      value.trim().length < min ||
      value.trim().length > max
    )
      fail("Проверьте введённые данные");
    return value.trim();
  };
  const https = (value) => {
    const url = new URL(text(value, 8, 1000));
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      fail("Укажите HTTP(S)-адрес");
    return url.href;
  };
  const json = (value, status = 200) =>
    new Response(JSON.stringify(value), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(input, globalThis.location.href);
    if (
      url.origin !== globalThis.location.origin ||
      !url.pathname.startsWith("/api/")
    )
      return originalFetch(input, options);
    if (options.signal?.aborted)
      throw new DOMException("Aborted", "AbortError");
    try {
      return await handle(
        url,
        options.method || "GET",
        options.body ? JSON.parse(options.body) : {},
        new Headers(options.headers),
      );
    } catch (error) {
      return json(
        { message: error.message, detail: error.message },
        error.status || 400,
      );
    }
  };
  globalThis.PORTFOLIO_DEMO = true;

  async function handle(url, method, body) {
    if (method === "GET" && state[url.pathname])
      return json(state[url.pathname]);
    if (url.pathname === "/api/targets" && method === "POST") {
      const name = text(body.name, 2, 80),
        address = https(body.url);
      if (state["/api/targets"].length >= 30) fail("Доступно до 30 целей", 409);
      const row = {
        id: crypto.randomUUID(),
        name,
        url: address,
        interval_minutes: Number(body.interval_minutes),
        render_js: Boolean(body.render_js),
        latest_snapshot: null,
      };
      state["/api/targets"].push(row);
      state["/api/overview"].targets++;
      return json(row, 201);
    }
    if (/^\/api\/targets\/[^/]+\/run$/.test(url.pathname))
      fail(
        "В браузере доступны сохранённые сравнения. Для нового сетевого снимка запустите сервер из README.",
        409,
      );
    fail("Не найдено", 404);
  }
})();
