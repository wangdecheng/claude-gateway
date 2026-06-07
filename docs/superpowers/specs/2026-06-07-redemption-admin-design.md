# Admin Redemption Code Design

## Goal

Add a working admin redemption-code management flow. Admins can generate a one-time redemption code for any positive amount. Users redeem the code into account balance through the existing user redemption page.

## Current State

- User redemption already exists through `POST /api/redeem` and `GET /api/redeem/history`.
- The database already has `redemption_codes` and `redemption_usages`.
- Admin navigation already links to `/admin/redemption`.
- `frontend/app/admin/redemption/page.tsx` does not exist, so the admin link currently returns 404.
- No admin API exists for generating redemption codes.

## Scope

In scope:

- Add an admin-only API to generate one redemption code.
- Add an admin page at `/admin/redemption`.
- Let admins enter amount and optional valid days.
- Default validity is 5 days.
- Return the full redemption code only in the generate response.
- Store only the bcrypt hash and prefix in the database.
- Keep redemption one-time use.
- Add focused backend and frontend tests.

Out of scope:

- Batch generation.
- Code export.
- Listing all generated codes.
- Manual revoke or delete.
- Custom code text entered by admin.

## Backend Design

Add a new router, likely `backend/app/routers/admin_redemption.py`, mounted under `/api/admin/redemption`.

Endpoint:

- `POST /api/admin/redemption`

Request:

- `amount`: integer cents, must be greater than 0.
- `expiresInDays`: integer days, optional, default 5, must be greater than 0.

Response:

- `id`
- `code`
- `codePrefix`
- `amount`
- `status`
- `expiresAt`
- `createdAt`

The endpoint requires `get_current_admin`. It generates a random code in the existing format `REDM-XXXX-XXXX-XXXX`, hashes the full code with the existing `hash_code()` helper, stores `code_prefix`, `amount`, `expires_at`, and `created_by`, then returns the full code once.

## Frontend Design

Add `frontend/app/admin/redemption/page.tsx` and `frontend/lib/api/admin/redemption.ts`.

The page follows the existing admin style:

- Header: "兑换码管理"
- Form fields:
  - Amount in yuan for admin usability, converted to cents before API call.
  - Valid days, default 5.
- Generate button.
- Error state using API error message.
- Success panel showing:
  - Full code in mono text.
  - Amount.
  - Expiry time.
  - Copy button.

The page does not persist or refetch generated full codes, because the full code is intentionally only available once.

## Data Flow

1. Admin opens `/admin/redemption`.
2. Admin enters amount and valid days.
3. Frontend posts to `/api/admin/redemption`.
4. Backend checks admin auth and validates inputs.
5. Backend creates a random code, stores only hash and prefix, and returns the full code.
6. Admin copies the code.
7. User redeems through existing `/redeem`.
8. Existing service marks the code `used`, writes `redemption_usages`, and increments user balance.

## Error Handling

- Non-admin users receive 403 from `get_current_admin`.
- Unauthenticated users receive 401.
- Invalid amount or invalid days returns validation error.
- Code generation should retry a small fixed number of times if an identical prefix already exists.
- User redemption errors stay unchanged.

## Testing

Backend tests should verify:

- Admin can generate a code.
- Default expiry is about 5 days from creation.
- Non-admin cannot generate a code.
- Invalid amount is rejected.
- Generated code can be redeemed by a user and credits balance.

Frontend tests should verify:

- The admin page renders the form.
- Submitting a valid amount calls the admin API hook.
- Success response displays the full code.

## Implementation Notes

- Do not change the existing user redemption route unless tests expose a real defect.
- Keep the generated code format compatible with `_CODE_PATTERN` in `redemption_service.py`.
- Keep money stored as integer cents.
- Do not add batch operations until the user asks for them.
