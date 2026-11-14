# Контракт API и интеграции

Машиночитаемый контракт: [openapi.json](../contracts/openapi.json), OpenAPI 3.1. Все endpoint являются проектными и ещё не запущены. Base URL `/api/v1`. Идентификаторы UUID, суммы — integer cents, время событий — ISO 8601 UTC.

## Авторизация

Private API принимает Bearer access token от доверенного identity provider; BFF использует серверную сессию. Проверка владельца обязательна даже после проверки JWT. Неавторизованный доступ к чужому id возвращает 404, чтобы не раскрывать существование объекта. 401 — нет действующей сессии, 403 — известный пользователю объект и недостаточное разрешение/entitlement.

Demo GET не требует авторизации и возвращает только закреплённый синтетический пример. Запись demo — локальная браузерная копия или отдельный изолированный сеанс с лимитами; private endpoint никогда не отключает auth из-за demo flag клиента.

## Семейства маршрутов

| Область | Операции |
|---|---|
| Cases | POST/GET cases, GET/PATCH/DELETE case |
| Documents | create upload intent, complete upload, list, source access |
| Jobs | получить статус и ошибку; повтор через новую идемпотентную операцию обработки |
| Extraction | запустить обработку выбранных документов; вернуть 202 и job id |
| Records | список, создание пользовательской записи, изменение через новую ревизию |
| Links | создание/отклонение/замена связи, включая allocation |
| Issues | список вопросов и resolution с ожидаемой ревизией |
| Calculations | поставить recalculation, получить summary и snapshots |
| Exports | создать из snapshot, получить статус и временную ссылку |
| Orders | получить предложение, подтвердить согласие, начать checkout, получить статус |
| Provider events | webhook по подписи провайдера, без пользовательского JWT |
| Support/privacy | дать/отозвать case grant, проверить status удаления |

## Конкурентные изменения

Мутации денежного смысла содержат `expected_revision` и `Idempotency-Key`. API блокирует case, сравнивает revision, валидирует изменение и коммитит новую revision вместе с job. При расхождении — 409 `REVISION_CONFLICT`, с current_revision. Клиент заново читает изменённые данные; автоматическое перетирание ответа запрещено.

Повтор с тем же ключом и телом возвращает прежний результат; с другим телом — 409 `IDEMPOTENCY_CONFLICT`. Идемпотентность не отменяет проверку текущего доступа. TTL ключей не может быть короче окна автоматических клиентских повторов; проектный минимум 24 часа, внешние платёжные события дедуплицируются без этого короткого TTL.

## Ошибки

```json
{
  "code": "REVISION_CONFLICT",
  "message": "The case changed. Review the latest version before saving.",
  "request_id": "opaque-request-id",
  "current_revision": 7,
  "retryable": false
}
```

Стабильные коды: VALIDATION_ERROR, UNSUPPORTED_DOCUMENT, UNREADABLE_DOCUMENT, PAGE_LIMIT, BUDGET_LIMIT, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, SOURCE_CHANGED, ACCESS_DENIED, CHECKOUT_UNAVAILABLE, PROVIDER_TEMPORARY_FAILURE, DELETION_PENDING. Стек исключения, prompt и текст документа не возвращаются в публичной ошибке.

422 — структурная/семантическая ошибка входа; 413 — размер; 415 — формат; 429 — лимит с Retry-After; 503 — временная недоступность. Failed asynchronous job имеет error_code и retryability; HTTP 200 его статуса не означает успешное выполнение.

## Upload contract

Intent принимает имя для отображения, предполагаемый MIME, размер и checksum. Сервер возвращает document_id, upload_id, URL, method, required_headers и expiry. Complete вызывает проверку фактического объекта, а не доверяет имени или checksum браузера. Не принимать произвольный remote URL. Source endpoint выдаёт краткую ссылку только после проверки владельца, document version и отсутствия удаления.

Ограниченный срок ссылки не делает её одноразовой. После финализации нельзя повторной загрузкой по старой ссылке подменить байты доказательства; использовать immutable final key/version, описанный в архитектуре.

## AI boundary

`extraction.schema.json` задаёт candidates и evidence с required полями и null для неизвестного. Модель не выбирает окончательную active_version и не создаёт оплачиваемый order. Суммы-кандидаты представлены исходными decimal strings; normalization преобразует их в cents после проверки локали.

schema_valid ≠ financially_correct. Проверяются сумма строк, соответствие источнику, тип начисления, повторные суммы, платежи и неоднозначность. Версии prompt/model/schema и стоимость попытки записываются; retry учитывается в бюджете.

## Payments и пилот

Платёжный провайдер и merchant account пока не выбраны. Доступность для страны/юридического статуса продавца проверяется до реальных оплат; нельзя предполагать доступность любого провайдера из одного тарифа. Hosted checkout получает order id и manifest hash. Подпись webhook проверяется по raw body, допускается повтор и доставка не по порядку.

Client redirect не устанавливает paid. Сумма и валюта сверяются с сохранённым offer. Неизвестные/неподходящие события ставятся на разбор. Refund сохраняет связь с тем же order. Исправление технической ошибки не требует новой оплаты. В demo платежи явно симулируются и не считаются продажами.

## Форматы отчётов

PDF: дата/cutoff, contractor, четыре блока результата, формулы, источники по страницам/строкам, происхождение, нерешённые вопросы, snapshot id/rules_version и оговорённый комплект. Гиперссылки на private sources требуют входа; экспорт не должен содержать долговечные публичные ссылки.

CSV: record_id, kind, amount_cents, currency, effective_date, origin, lifecycle, source_reference, snapshot_id. Текстовые ячейки экранируются против spreadsheet formula injection (`=`, `+`, `-`, `@`, tab и управляющие префиксы). Числовые суммы пишутся числовыми; защитное экранирование текста не искажает отрицательные денежные значения.
