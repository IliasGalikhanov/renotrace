# Этап 4 — API и интерактивное демо RenoTrace

Дата: 14 ноября 2026. Рабочая папка: `D:\Новая папка\3 курс\Business Cup\renotrace`.

## Реализовано

Вместо Coming soon работает английское публичное демо: Try sample, выбор FIN-01/FIN-16/FIN-11, четыре блока результата, история записей, раскрытие расчёта и читаемых синтетических источников, вопросы, выбор получателя перевода и Reset sample. Метка Synthetic demo постоянно видна в закреплённой шапке.

FastAPI предоставляет список примеров, исходный пример и перерасчёт. Next.js вызывает API через серверный BFF с BACKEND_URL. Сервер принимает только ограниченные типизированные действия, самостоятельно загружает исходный пример и запускает настоящий normalization → ledger. Денежных формул в TypeScript нет — только форматирование возвращённых центов.

Каждый запрос использует новую независимую историю; fixtures не меняются, посетители не разделяют решения. Повторный выбор в одной области заменяет предыдущую команду этого запроса. Доменные проверки актуальности сохранены; новый demo draft получает отдельную revision и соответствующее подтверждение, без перебазирования прежних связей. Это **расчёт без сохранения**, не persistent cases, транзакции или snapshots.

Неопределённые вопросы и incomplete_metrics передаются без потери. Неполные показатели помечены Provisional, отсутствующие суммы и условия — Unknown. Условия во всех трёх примерах не заданы; срок платежа и выполнение работ не выдумываются. Суммы раскрываются до участвующих записей и текстов источников; credit $800 относится к обязательствам, cumulative increment — к предыдущей оценке, а остаток счёта — к его собственным распределениям.

При новом запросе прежние цифры скрываются сразу. Используются AbortController и независимый номер запроса, поэтому старый ответ не может подменить новый даже без транспортной отмены. Ошибки показывают Retry; повтор сохраняет ожидающий выбор. Клавиатура работает через native buttons/radios/details и видимый фокус.

Подготовлены фактический [OpenAPI](../contracts/demo.openapi.json), [demo-контракт](DEMO_API_CONTRACT.md), [инструкции Vercel/контейнера](DEPLOYMENT.md), `.dockerignore`, Dockerfile с lockfile и непривилегированным пользователем, `/healthz`, host `0.0.0.0` и настраиваемый PORT. Платные ресурсы и hosted deployment не создавались.

## Результаты проверок

- **347 Python-тестов прошли**: 322 прежних и 25 новых API-тестов. Включены параллельные независимые запросы, запреты произвольных данных, реальный пересчёт, происхождение сумм и соответствие OpenAPI приложению.
- Покрытие ledger + normalization + demo с ветвлениями: **99,86%** при пороге 95%; demo-модуль — 100% исполняемых строк и ветвей. Полнота тестов не равна гарантии отсутствия ошибок.
- **30 Playwright-проверок прошли**: 10 сценариев × 360/768/1440 px, Chromium 159 (Playwright 1.65.1). Проверены путь от открытия до выбора, источники, keyboard, Reset/reload, изоляция двух контекстов, ошибки API и retry, неверные действия/маршруты/body, запоздавшие ответы решений и сценариев с отключённой транспортной отменой.
- FIN-01: запрос **$5 500**, остаток **$4 700**, раскрывается зачёт **$800**.
- FIN-16: исходно **$7 000 / Provisional** → contractor **$5 000** → another recipient **$7 000**. I don't know и Reset возвращают **$7 000 / Provisional**. Другая вкладка/контекст остаётся независимой.
- FIN-11: новое начисление **$8 500**, начислено **$13 500**, положительные остатки **$10 500**, позиции **$2 000 / $8 500**.
- Ruff check/format, strict mypy, TypeScript приложения и e2e, Prettier, Next.js production build — пройдены.
- HTTP smoke обновлён: реальные FastAPI/Next.js, health, страница и BFF POST с пересчётом **700000 → 500000 cents** — пройдены.
- Проверка проектной документации выполняется `validate_spec.py` в portable режиме; исходные private-контракты не объявлены реализованными.

CI расширен: Windows/Linux повторяют тесты, build, smoke, Playwright; Linux дополнительно собирает контейнер и проверяет `/healthz` и FIN-11 на PORT=8080. Локальный Docker Engine недоступен; проверено существование закреплённого тега Python. Итог конкретного CI-запуска и commit hash передаются после push; [workflow](https://github.com/IliasGalikhanov/renotrace/actions/workflows/checks.yml).

## Визуальная проверка

Сохранены девять полноразмерных скриншотов. Визуально проверены 360, 768 и 1440 px: суммы читаемы, длинные названия переносятся, управление доступно, горизонтального переполнения нет. В финальном просмотре проверены FIN-01/1440, FIN-11/768, FIN-16/360; также просмотрен FIN-16 на всех трёх размерах. Playwright отдельно проверяет отсутствие горизонтальной прокрутки и видимость Synthetic demo для каждого примера/размера.

| Пример | 360 px | 768 px | 1440 px |
|---|---|---|---|
| FIN-01 | [mobile](screenshots/stage4/FIN-01-chromium-360.png) | [tablet](screenshots/stage4/FIN-01-chromium-768.png) | [desktop](screenshots/stage4/FIN-01-chromium-1440.png) |
| FIN-16 | [mobile](screenshots/stage4/FIN-16-chromium-360.png) | [tablet](screenshots/stage4/FIN-16-chromium-768.png) | [desktop](screenshots/stage4/FIN-16-chromium-1440.png) |
| FIN-11 | [mobile](screenshots/stage4/FIN-11-chromium-360.png) | [tablet](screenshots/stage4/FIN-11-chromium-768.png) | [desktop](screenshots/stage4/FIN-11-chromium-1440.png) |

## Запуск и тестирование

После установки по README, из корня проекта, в отдельных терминалах:

```powershell
.\scripts\uv.ps1 run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Copy-Item .env.example apps/web/.env.local
npm run dev
```

Открыть http://127.0.0.1:3000. Проверки:

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo --cov-report=term-missing
.\scripts\uv.ps1 run --locked ruff check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked python tools/validate_spec.py
npm run build
npm run typecheck
npm run format:check
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
npx playwright install chromium
npm run test:e2e
```

## Ограничения

Только три синтетических примера и один вид редактируемого решения FIN-16. Данные не сохраняются; нет регистрации, private cases, загрузки файлов, OCR, БД, постоянных snapshots или пользовательских документов. Даты аудита demo-ответов могут отличаться между равными запросами; финансовые значения и fingerprint при одинаковых действиях одинаковы.

Проверялся Chromium на трёх viewport, не реальные мобильные устройства, Firefox/WebKit или все вспомогательные технологии. Vercel-конфигурация подготовлена по официальной документации, но в аккаунт не разворачивалась. Лимиты/защита нагрузки платформы остаются настройками будущего хостинга; application rate limiting не добавлен. Источники — явно вымышленные фрагменты, а не юридически подтверждённые документы.

Следующий этап не начат.
