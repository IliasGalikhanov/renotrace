import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const valid =
    (path.length === 1 &&
      path[0] === "scenarios" &&
      request.method === "GET") ||
    (path[0] === "scenarios" &&
      /^[A-Z0-9-]{1,32}$/.test(path[1] ?? "") &&
      ((path.length === 2 && request.method === "GET") ||
        (path.length === 3 &&
          path[2] === "calculate" &&
          request.method === "POST")));
  if (!valid)
    return NextResponse.json(
      { detail: "Unknown demo route" },
      { status: 404, headers },
    );
  const backend = process.env.BACKEND_URL;
  if (!backend)
    return NextResponse.json(
      { detail: "Demo service is not configured" },
      { status: 503, headers },
    );
  let body: string | undefined;
  if (request.method === "POST") {
    const reader = request.body?.getReader();
    let size = 0;
    const chunks: Uint8Array[] = [];
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 8192) {
          await reader.cancel();
          return NextResponse.json(
            { detail: "Demo request is too large" },
            { status: 413, headers },
          );
        }
        chunks.push(value);
      }
    }
    body = Buffer.concat(chunks).toString("utf8");
    try {
      JSON.parse(body);
    } catch {
      return NextResponse.json(
        { detail: "Invalid JSON" },
        { status: 400, headers },
      );
    }
  }
  try {
    const response = await fetch(
      `${backend.replace(/\/$/, "")}/api/demo/${path.join("/")}`,
      {
        method: request.method,
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
        redirect: "error",
      },
    );
    if (!response.ok) {
      const status = [404, 422].includes(response.status)
        ? response.status
        : 502;
      return NextResponse.json(
        {
          detail:
            status === 422
              ? "This demo action was not accepted"
              : status === 404
                ? "Unknown demo scenario"
                : "Demo service is temporarily unavailable",
        },
        { status, headers },
      );
    }
    return NextResponse.json(await response.json(), { headers });
  } catch {
    return NextResponse.json(
      { detail: "Demo service is temporarily unavailable. Please retry." },
      { status: 502, headers },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
