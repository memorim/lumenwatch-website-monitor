# Публичное размещение LumenWatch

Эта инструкция закрывает границу, которая не проверяется GitHub Pages: HTTPS, операторский токен и изолированный Playwright-worker на выделенном Docker-узле.

## Подготовка узла

Нужны Linux, Docker с cgroup v2 и Caddy или другой TLS-прокси. Не размещайте worker на общем хосте с недоверенными арендаторами: основной контейнер получает доступ к Docker socket, чтобы запускать одноразовый браузерный контейнер.

Соберите образ браузера из корня репозитория:

```bash
docker build -f worker/Dockerfile -t lumenwatch-browser:1.64.1 .
```

Создайте файл окружения рядом с Compose-файлом:

```bash
LUMENWATCH_PUBLIC_ORIGIN=https://lumenwatch.example.com
LUMENWATCH_AUTH_TOKEN=$(openssl rand -hex 32)
```

Токен должен храниться только в защищённом окружении процесса. Не помещайте его в Git, URL или HTML.

## Запуск

```bash
docker compose -f deploy/docker-compose.public.yml --env-file .env.public up -d --build
```

Проксируйте только локальный порт приложения через [Caddyfile.example](../deploy/Caddyfile.example). Публичный интерфейс должен использовать HTTPS origin, совпадающий с `LUMENWATCH_PUBLIC_ORIGIN`.

## Проверка

После запуска проверьте:

1. `GET /api/health` через HTTPS возвращает успешный ответ.
2. Запросы без аутентификации получают HTTP 401. В браузере введите имя `operator` и пароль из `LUMENWATCH_AUTH_TOKEN`; API также принимает Bearer-токен.
3. HTTP-цель с приватным адресом и редиректом на приватный адрес отклоняется.
4. Browser capture создаёт отдельный контейнер без сети, с read-only корнем, UID 1000 и установленными лимитами.
5. После захвата контейнер удаляется, а база и снимки сохраняются после перезапуска Compose.

Повторите на целевом узле:

```bash
RUN_DOCKER_BROWSER_TESTS=1 python -m pytest tests/test_isolated_browser.py
```

Эта конфигурация не создаёт DNS-записи, сертификаты, Docker-хост или секреты автоматически. Проверку внешнего TLS-прокси и встроенного операторского входа нужно выполнить после публикации.
