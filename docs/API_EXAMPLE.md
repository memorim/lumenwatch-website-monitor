# Пример API

Ответ получен при локальном запуске проверяемой версии. Данные демонстрационные.

```http
GET /api/overview HTTP/1.1
Host: localhost:8020
```

HTTP 200

```json
{
  "targets": 2,
  "active_targets": 2,
  "checks": 3,
  "changes": 1,
  "average_response_ms": 432.0
}
```
