# Пример минимального экспорта

Иллюстративный JSON-снимок для smoke-теста конвертера.

## Использование

```bash
opencode-md docs/skills/minimal-session.json -o /tmp/out.md
```

## Ожидаемый результат

Один Markdown-файл с заголовком «Пример сессии», двумя блоками (User /
Assistant) и секцией `🔧 tool: bash` с JSON-аргументами и выводом.

## Что внутри

- `text` от пользователя и от ассистента;
- `reasoning` (мысли модели);
- `tool: bash` с input + output + title + metadata.

Все остальные типы частей (`file`, `agent`, `subtask`, `patch`, `snapshot`,
`step-start`, `step-finish`) подробно описаны в
[`parts-and-sanitize.md`](parts-and-sanitize.md).
