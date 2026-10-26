"""Build an isolated static demo; never reads a runtime database or changes the API."""

import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "app/static"
output = root / "_site"
output.mkdir(exist_ok=True)
shutil.copytree(source, output, dirs_exist_ok=True)
seed = json.loads((root / "demo/seed.json").read_text(encoding="utf8"))
(output / "seed.js").write_text(
    "globalThis.DEMO_SEED = " + json.dumps(seed, ensure_ascii=False) + ";\n", encoding="utf8"
)
shutil.copyfile(root / "demo/browser.js", output / "demo.js")
index = output / "index.html"
html = index.read_text(encoding="utf8").replace("/static/", "")
html = html.replace(
    "<script ", '<script src="seed.js"></script><script src="demo.js"></script><script ', 1
)
html = (
    html.replace(
        "<script>", '<script src="seed.js"></script><script src="demo.js"></script><script>', 1
    )
    if 'src="seed.js"' not in html
    else html
)
html = html.replace(
    "</body>",
    '<footer class="browser-scope" '
    'style="padding:16px;text-align:center;font:12px/1.5 system-ui">Изменения в '
    "этой версии хранятся в текущей вкладке. <a "
    'href="https://github.com/memorim/lumenwatch-website-monitor#readme">Исходный '
    "код и запуск сервера</a></footer></body>",
)
html = html.replace('href="/"', 'href="./"').replace(
    'href="/docs"', 'href="https://github.com/memorim/lumenwatch-website-monitor#readme"'
)
html = html.replace("Start watching", "Добавить в текущую сессию").replace(
    "Start monitoring →", "Добавить в текущую сессию →"
)
html = html.replace('id="check-now">Проверить сейчас', 'id="check-now">О сетевых проверках')
index.write_text(html, encoding="utf8")
app = output / "app.js"
if app.exists():
    text = app.read_text(encoding="utf8")
    text = text.replace("Run check", "О сетевой проверке").replace(
        " is now being watched.",
        " добавлен в текущую сессию; сетевые проверки доступны при запуске сервера.",
    )
    text = text.replace(
        "Капсула зашифрована и отправлена на орбиту.",
        "Капсула зашифрована в памяти вкладки. Сохранится до перезагрузки страницы.",
    )
    text = text.replace(
        "Демо-заявка сохранена. Уведомления менеджеру не отправляются.",
        "Заявка сохранена в текущей вкладке. Контакты не отправлены менеджеру.",
    )
    text = text.replace("Демо-заказ №", "Заказ в текущей вкладке №")
    app.write_text(text, encoding="utf8")
print("Built isolated browser demo:", root.name)
