import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify, importSPKI, type KeyLike } from "jose";

// 公钥只用于验签,即使泄露也无法伪造 token。
// 从 .env 以 base64 注入(避开 systemd EnvironmentFile 对 \ 的转义),此处 base64 decode 还原 PEM。
// 后端: RS256 私钥签发 -> JWT -> 此处用公钥验签。
// Public key is stored base64-encoded in the shared env file (~/.fcc/.env).
// Same env var the backend signs with (config/settings.py:JWT_PUBLIC_KEY).
const PUBLIC_KEY_PEM = process.env.JWT_PUBLIC_KEY
  ? Buffer.from(process.env.JWT_PUBLIC_KEY, "base64").toString("utf-8")
  : "";

// Paths that do NOT require authentication
const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];

// Paths that require admin role
const ADMIN_PATHS = ["/admin"];

let publicKeyPromise: Promise<KeyLike> | null = null;
function getPublicKey() {
  if (!publicKeyPromise) {
    publicKeyPromise = importSPKI(PUBLIC_KEY_PEM, "RS256").catch((err) => {
      publicKeyPromise = null; // 重置以便重试
      throw err;
    });
  }
  return publicKeyPromise;
}

async function verifyJwt(token: string) {
  try {
    const key = await getPublicKey();
    const { payload } = await jwtVerify(token, key, { algorithms: ["RS256"] });
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
    "/((?!_next/static|_next/image|favicon.ico|api).*)",
  ],
};
