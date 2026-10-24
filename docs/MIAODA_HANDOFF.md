# 秒哒后续对接边界

2026-10-24，用户确认先开发 React + TypeScript 本地前端、后续对接秒哒。此选择允许本轮本地实现，不等于取消秒哒目标或确认赛事允许独立后端。

## 已可复用

- OpenAPI：docs/openapi.json；生成的 TypeScript 类型：frontend/src/generated/api.d.ts。
- 会话/CSRF/幂等/错误适配：frontend/src/lib/api.ts。现阶段使用浏览器同源 Cookie，不在前端暴露数据库或模型凭据。
- 通用场景表单配置：frontend/src/lib/model.ts；三份业务 fixture、统一 SceneSpec、两类服务器计算引擎。
- 草稿只读 preview、用户确认保存、不可变分支、比较、手动挑战与观察等真实 API。
- 奶油白/暖橙/鼠尾草绿的轻量响应式组件与 CSS，可按秒哒实际可用框架迁移，不要求重写已可用的秒哒资源。

## 待获得和核实

1. 秒哒实际项目链接/可编辑资源或导出源码，及其框架、构建命令、插件入口。
2. 外部业务 API 的请求/响应映射；插件是否支持透传匿名 Cookie 和自定义 X-CSRF-Token/Idempotency-Key。
3. 秒哒 H5 域名、API 域名与同站关系；若跨站，需实测 Secure/SameSite、credentials、CORS、CSRF 和浏览器限制。不能只把 CORS 改为 `*` 或把访问令牌塞到 URL。
4. 实际发布权限、HTTPS、后端托管与有效赛事规则。不在未获授权时发布公网或创建收费资源。

官方核实入口仍为 V4.0 的三条百度云文档。本轮重新请求全部返回代理 `403 Domain forbidden / Tunnel connection failed`，未获取正文；没有绕过代理或用非官方材料替代结论。本地浏览器的同源代理通过不证明秒哒跨站集成可用。

获得资源后，先跑最小的“匿名会话 → 新建项目 → 确认场景 → preview/simulate → 刷新读回”联调，再迁移 UI。保留原 API 权限与版本语义，不能为接平台而改成任意 SQL、任意 URL 或客户端声明外部核验事实。
