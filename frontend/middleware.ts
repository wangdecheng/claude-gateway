import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";

const JWT_SECRET = new TextEncoder().encode(
  process.env.JWT_SECRET || "dev-secret-change-in-production"
);

// Paths that do NOT require authentication
const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];

// Paths that require admin role
const ADMIN_PATHS = ["/admin"];

async function verifyJwt(token: string) {
  try {
    const { payload } = await jwtVerify(token, JWT_SECRET);
    return payload as { user_id: number; role: string };
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths without authentication
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    const token = request.cookies.get("high_api_session")?.value;
    // If already logged in, redirect to dashboard
    if (token) {
      const payload = await verifyJwt(token);
      if (payload) {
        if (payload.role === "admin") {
          return NextResponse.redirect(new URL("/admin", request.url));
        }
        return NextResponse.redirect(new URL("/", request.url));
      }
    }
    return NextResponse.next();
  }

  // Require authentication for all other paths
  const token = request.cookies.get("high_api_session")?.value;
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const payload = await verifyJwt(token);
  if (!payload) {
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete("high_api_session");
    return response;
  }

  // Admin route protection
  if (ADMIN_PATHS.some((p) => pathname.startsWith(p))) {
    if (payload.role !== "admin") {
      return NextResponse.json({ error: "无权访问" }, { status: 403 });
    }
  }

  // Inject X-User-ID header for BFF API routes
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("X-User-ID", String(payload.user_id));
  requestHeaders.set("X-User-Role", payload.role);

  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/auth).*)",
  ],
};
