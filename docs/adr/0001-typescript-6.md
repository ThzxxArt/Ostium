# ADR 0001：Vue 工具链使用 TypeScript 6.0.3

- 状态：已接受
- 日期：2026-11-12
- 背景：PLAN.md 锁定 TypeScript 7.0.2 和 vue-tsc 3.1.0。

## 问题

TypeScript 7.0 移除了 `typescript/lib/tsc` 导出。`vue-tsc`（包括最新的 3.3.x）会解析该路径，在类型检查任何组件之前就以 `ERR_PACKAGE_PATH_NOT_EXPORTED` 失败。

## 决定

v0.1.0 固定 TypeScript **6.0.3** 和 `vue-tsc` **3.3.14**。这是当前能对 Vue SFC 和 Node/Vite 配置做类型检查的最近兼容组合。应用代码仍是标准 TS/ES2022；等 `vue-tsc` 支持新的 package exports 后可以升级到 TS 7。

## 影响

- `npm run typecheck` 和 `npm run build` 在 Node 24.19.0 下正常工作。
- 计划中的 TS 版本被本 ADR 取代；运行时行为不变。
- CI 通过 `package-lock.json` 固定相同版本。
