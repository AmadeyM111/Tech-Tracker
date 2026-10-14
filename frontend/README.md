# Frontend

Vite + React 18 + TypeScript (strict) + TanStack Query v5 + react-router-dom v7.
Версии зависимостей зафиксированы в `package-lock.json` (план §7.2). Требуется
Node.js `^20.19.0 || >=22.12.0` (образ сборки — `node:22-alpine`).

Команды (из каталога `frontend/`):

```bash
npm ci                # установка по package-lock.json
npm run dev           # dev-сервер http://localhost:5173, прокси /api -> http://localhost:8000
npm run lint          # eslint (strict, any запрещён)
npm run typecheck     # tsc --noEmit
npm test              # vitest run (jsdom, сеть в тестах отключена)
npm run build         # tsc --noEmit && vite build -> dist/
npm run gen:api       # типы из ../docs/api/openapi.json -> src/shared/api/schema.d.ts
```

Требования к коду — в `AGENTS.md`, раздел «Фронтенд». Строки интерфейса — только из
словаря `src/shared/i18n/` (NFR-6); в `.tsx` кириллических литералов быть не должно.
