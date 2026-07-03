import { NextResponse, type NextRequest } from "next/server";

/**
 * SEC-2: inject the internal API key into same-origin /api/* proxy calls SERVER-SIDE,
 * so cqp-api can gate its compute-heavy endpoints while the key never reaches the
 * browser bundle. `INTERNAL_API_KEY` is a plain server env var (NOT NEXT_PUBLIC_*), read
 * only here in middleware.
 *
 * Security: ALWAYS strip any client-supplied `x-internal-key` first (a browser must not
 * be able to spoof it), then set the trusted value only if the server env is present.
 */
export const config = { matcher: "/api/:path*" };

export function middleware(req: NextRequest) {
  const requestHeaders = new Headers(req.headers);
  requestHeaders.delete("x-internal-key"); // never trust an inbound key
  const key = process.env.INTERNAL_API_KEY;
  if (key) requestHeaders.set("x-internal-key", key);
  return NextResponse.next({ request: { headers: requestHeaders } });
}
