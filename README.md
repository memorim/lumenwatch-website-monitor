# LumenWatch — мониторинг изменений сайтов

Сохраняет версии страниц и показывает, что изменилось между проверками.

**Проект:** Самостоятельная разработка.

![CI](https://github.com/memorim/lumenwatch-website-monitor/actions/workflows/ci.yml/badge.svg)

![Компьютерная версия](docs/desktop.png)

<img src="docs/mobile.png" width="320" alt="Мобильная версия">

[Короткая демонстрация сценария](docs/demo.gif) · [Видео: около минуты](docs/walkthrough.webm) · [Разбор проекта](docs/CASE_STUDY.md)

## Что работает
- HTTP-захват, текстовые различия, история снимков и уровни изменений.
- Адаптивная панель, REST API, MCP-инструменты, опциональный планировщик.
- Опциональный захват JavaScript-страниц через Playwright.

## Стек
Python, FastAPI, HTTPX, Beautiful Soup, SQLite, Playwright, MCP.

## Запуск и проверка
Python 3.12.14.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -c requirements-lock.txt -e ".[dev]"
python -m ruff check .
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8020
```

## Технические решения
- Бизнес-логика общая для REST и MCP.
- Планировщик выключен по умолчанию; недоступная цель обрабатывается как отдельная ошибка.

## Подробности
[API, конфигурация и исходные инструкции](docs/TECHNICAL.md).

[Результаты проверки этой версии](docs/VERIFICATION.md).

[Пример запроса и ответа API](docs/API_EXAMPLE.md).

[Автоматизированные проверки и замеры](docs/SYNTHETIC_METRICS.json) · [Подготовка к собеседованию](docs/INTERVIEW.md)

## Проверки и обновления
CI проверяет проект и ссылки на локальные материалы. Dependabot предлагает обновления зависимостей и Actions. [История изменений](CHANGELOG.md).

[Контракты API и обновление базы](docs/COMPATIBILITY.md): `python tests/check_contract.py && python tests/check_upgrade.py`.
