export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const backend = env.BACKEND_URL;
    if (!backend) {
      return new Response("BACKEND_URL is not configured.", { status: 500 });
    }

    const target = new URL(url.pathname + url.search, backend);

    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", url.host);
    headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    const response = await fetch(target, init);

    const responseHeaders = new Headers(response.headers);
    responseHeaders.set("X-Proxy-By", "Cloudflare");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  },
};
