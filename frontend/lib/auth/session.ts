/**
 * Session helpers — parse JWT payload client-side from cookie.
 * The cookie is HttpOnly so we can't read it directly;
 * we rely on the API to tell us who we are.
 */

export interface Session {
  userId: number;
  role: "user" | "admin";
}

let cachedSession: Session | null = null;

export function setSession(session: Session | null) {
  cachedSession = session;
}

export function getSession(): Session | null {
  return cachedSession;
}

export function isAuthenticated(): boolean {
  return cachedSession !== null;
}

export function isAdmin(): boolean {
  return cachedSession?.role === "admin";
}
