# Этап 2.1: неполнота при конфликте подтверждений платежа

Исправлена ошибка в `normalization`, версия результата — `normalization-0.1.1`. Другие доменные модули не добавлялись, денежные формулы ledger не менялись.

## Воспроизведение и результат

Структурированный FIN-08: два наблюдения одной банковской операции; для `import-b` добавлено текущее `confirm_semantics/reject`. До исправления регрессионные тесты падали: `import-a` имел причину `UNRESOLVED_TRANSACTION`, но вопросов не было и `incomplete=False`.

После исправления консервативное исключение группы сохраняется: net paid = **0**, remainder = **1 000 000** центов. Возвращается `TRANSACTION_REVIEW_CONFLICT` с обеими записями и связанными решениями. `incomplete=True`, обе денежные метрики обозначены неполными. Записи сохраняют разные причины: `UNRESOLVED_TRANSACTION` и `REJECTED_BY_USER`.

При повторном согласовании обеих записей в новой case revision: один платёж **300 000** центов, остаток **700 000**, вопрос исчезает. При двух явных текущих отклонениях: обе записи `REJECTED_BY_USER`, платёж не учитывается, ложный неразрешённый конфликт не создаётся. Непроверенные и устаревшие подтверждения сохраняют вопросы.

## Проверки

- 8 новых регрессионных/генеративных тестов: исходное воспроизведение и явное принятие второй стороны, перестановки, повторное согласование, намеренное отклонение всей группы, unreviewed/stale и комбинации состояний.
- Общий инвариант применяется во вспомогательном запуске каждого теста нормализации: каждый `UNRESOLVED_TRANSACTION` имеет вопрос с ID записи и влиянием на net paid и remainder; соответствующие флаги неполноты установлены.
- 138 тестов нормализации проходят. Полный локальный прогон — **229 passed**, покрытие строк/ветвей ledger + normalization — **99,76%**. Ruff lint/format, mypy strict и проверка спецификации проходят. CI на Windows/Linux проверяется после push.
- Контракт обновлён в [NORMALIZATION_CONTRACT.md](NORMALIZATION_CONTRACT.md). Связанные решения в вопросе включают контекст устаревших подтверждений, но не считаются автоматически применёнными.

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov-report=term-missing
.\scripts\uv.ps1 run --locked ruff check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked mypy
```

Границы этапа 2 сохранены: структурированный вход, без OCR, БД, UI, накопительных начислений и allocations. Следующий этап не начат. CI: [GitHub Actions](https://github.com/IliasGalikhanov/renotrace/actions).
