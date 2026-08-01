# CONTEXT — Domain Glossary

This file is a glossary only. It captures the canonical meaning of terms in the
`high-api` (cloude-gateway) domain that are ambiguous or overloaded in the code.
No implementation details, no specs, no decisions (those live in `docs/adr/`).

## Provider

A `Provider` is one upstream AI supplier **channel instance** — a concrete,
addressable endpoint (base URL + key pool) that speaks a particular adapter
protocol. It is **not** the adapter type itself; the same adapter type can be
served by multiple `Provider` rows.

The `Provider` table carries four name-like fields. Their meanings are fixed
here because the codebase overloads "渠道" and "名称":

### `id` — primary key / identity
The only stable identity of a Provider. Used as the foreign key from
`model_providers.provider_id` and `provider_keys.provider_id`. Everything else
is just a label.

### `name` — adapter / upstream type (mutable, **not** unique)
A label matching a key in `providers/registry.py::PROVIDER_FACTORIES`
(`deepseek`, `glm`, `minimax`, `volcengine`). It tells the runtime **which
adapter factory** to instantiate. It is **repeatable**: multiple `Provider` rows
may share the same `name` (e.g. two `GLM` providers — one official, one
volcengine-hosted). It is *not* a uniqueness constraint and *not* the row's
identity, despite the comment in `ProviderUpdate` that says "Name changes are
not supported via update to avoid uniqueness issues" — that comment is
misleading; `name` has no unique constraint in practice.

> Note: the on-disk `name` values use inconsistent casing (`GLM`, `miniMax`,
> `minimax`) which does not always match the lowercase factory keys. This is a
> known latent issue, out of scope of the current change.

### `channel_name` — user-facing display label (mutable)
The human-readable name shown to **end users** in `/providers/active`
(e.g. `glm官方`, `sub2api`, `火山GLM`). This is the only name users ever see.
The user-side schemas enforce this: `backend/app/schemas/channel.py` is
commented "never expose provider.name".

### `adapter` — **deprecated** field
A two-valued classifier (`openai-chat-completions` | `anthropic-messages`). All
upstream adapters are now translated to the `anthropic-messages` protocol
outward; `name` is the real adapter selector, and `adapter` carries no actual
behavioral weight. It is scheduled for removal (see ADR pending) but still
exists in schema, forms, and the provider-list table column. New providers
default to `anthropic-messages`.

## "渠道" (channel) — disambiguation

The word "渠道" is used for **two different things** in this codebase; they
must not be conflated:

1. **`Provider.channel_name`** — the display label field on a Provider row
   (see above). "渠道名" in the admin provider-management UI refers to this.

2. **The `/admin/channels` page & `model_providers` table** — a **route
   binding** between a `Model` and a `Provider` (which upstream provider serves
   which model, with which `provider_model` name). Despite the page being
   called "渠道管理" / "渠道配置", it manages `ModelProviderRoute` rows, **not**
   channels. `channel_name` and `multiplier` shown there are pulled *from the
   bound Provider*, not stored on the route. See
   `backend/app/schemas/admin_channel.py` header comment.

When someone says "渠道" without qualification, ask: *the Provider's
`channel_name` field, or a Model↔Provider route?*
