# ADR 0001: TypeScript 6.0.3 for the Vue toolchain

- Status: accepted
- Date: 2026-11-12
- Context: PLAN.md locks TypeScript 7.0.2 and vue-tsc 3.1.0.

## Problem

TypeScript 7.0 removes the `typescript/lib/tsc` export. `vue-tsc` (including the
latest 3.3.x) resolves that path and fails with
`ERR_PACKAGE_PATH_NOT_EXPORTED` before it can type-check any component.

## Decision

Pin TypeScript **6.0.3** and `vue-tsc` **3.3.14** for v0.1.0. This is the
nearest compatible toolchain that type-checks the Vue SFCs and the Node/Vite
config. Application code remains standard TS/ES2022 and can move to TS 7 once
`vue-tsc` supports the new package exports.

## Consequences

- `npm run typecheck` and `npm run build` work on Node 24.19.0.
- The plan's TS version is superseded by this ADR; no runtime behavior changes.
- CI pins the same versions through `package-lock.json`.
