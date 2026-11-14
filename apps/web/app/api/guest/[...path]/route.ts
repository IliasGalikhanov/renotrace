import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;
const cookie =
  process.env.NODE_ENV === "production"
    ? "__Host-renotrace"
    : "renotrace-guest";
const headers = { "Cache-Control": "no-store" };

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const session =
    path.length === 1 && path[0] === "session" && request.method === "POST";
  const project =
    path[0] === "projects" && /^[a-f0-9-]{36}$/.test(path[1] ?? "");
  const valid =
    session ||
    (project &&
      ((path.length === 2 && ["GET", "DELETE"].includes(request.method)) ||
        (path.length === 3 &&
          ["review", "tickets", "replies", "attachments", "rechecks"].includes(
            path[2],
          ) &&
          request.method === "POST") ||
        (path[2] === "snapshots" &&
          request.method === "GET" &&
          (path.length === 3 ||
            (path.length === 4 && /^[a-f0-9-]{36}$/.test(path[3])))) ||
        (path[2] === "comparisons" &&
          path.length === 4 &&
          request.method === "GET" &&
          /^[a-f0-9-]{36}$/.test(path[3])) ||
        (path.length === 5 &&
          request.method === "POST" &&
          ((path[2] === "rechecks" &&
            /^[a-f0-9-]{36}$/.test(path[3]) &&
            ["package", "run"].includes(path[4])) ||
            (path[2] === "questions" &&
              /^q-[a-f0-9]{32}$/.test(path[3]) &&
              path[4] === "state") ||
            (path[2] === "replies" &&
              /^[a-f0-9-]{36}$/.test(path[3]) &&
              path[4] === "edit")))));
  if (!valid)
    return NextResponse.json(
      { detail: "Unknown review route" },
      { status: 404, headers },
    );
  if (request.method !== "GET") {
    const origin = request.headers.get("origin");
    let sameOrigin = false;
    try {
      const parsed = new URL(origin ?? "");
      sameOrigin =
        parsed.host === request.headers.get("host") &&
        parsed.protocol === request.nextUrl.protocol;
    } catch {
      /* Invalid or missing Origin fails closed. */
    }
    if (!sameOrigin)
      return NextResponse.json(
        { detail: "Same-origin request required" },
        { status: 403, headers },
      );
  }
  const backend = process.env.BACKEND_URL;
  if (!backend)
    return NextResponse.json(
      { detail: "Private review service is not configured" },
      { status: 503, headers },
    );
  const secret = request.cookies.get(cookie)?.value;
  let body: string | undefined;
  if (request.method === "POST" && !session) {
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader)
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 128 * 1024) {
          await reader.cancel();
          return NextResponse.json(
            { detail: "Review request is too large" },
            { status: 413, headers },
          );
        }
        chunks.push(value);
      }
    body = Buffer.concat(chunks).toString("utf8");
  }
  try {
    const upstream = await fetch(
      `${backend.replace(/\/$/, "")}/api/guest/${path.join("/")}`,
      {
        method: request.method,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(23_000),
        headers: {
          "Content-Type": "application/json",
          ...(secret ? { Authorization: `Bearer ${secret}` } : {}),
        },
      },
    );
    if (upstream.status === 204) {
      const response = new NextResponse(null, { status: 204, headers });
      if (request.method === "DELETE") response.cookies.delete(cookie);
      return response;
    }
    const data = await upstream.json();
    if (!upstream.ok)
      return NextResponse.json(
        {
          detail:
            typeof data.detail === "string"
              ? data.detail
              : "Check the record values and try again",
        },
        {
          status: [400, 404, 409, 413, 422, 429, 503].includes(upstream.status)
            ? upstream.status
            : 502,
          headers,
        },
      );
    if (session) {
      const response = NextResponse.json(
        { project_id: data.project_id },
        { headers },
      );
      response.cookies.set(cookie, data.token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "strict",
        path: "/",
        maxAge: 86400,
      });
      return response;
    }
    if (path[2] === "tickets")
      return NextResponse.json(
        {
          ...data,
          transfer_url: `${backend.replace(/\/$/, "")}/api/guest/transfer`,
        },
        { headers },
      );
    return NextResponse.json(data, { headers });
  } catch {
    return NextResponse.json(
      {
        detail:
          "The private review service is starting or unavailable. Please retry in a moment.",
      },
      { status: 502, headers },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
