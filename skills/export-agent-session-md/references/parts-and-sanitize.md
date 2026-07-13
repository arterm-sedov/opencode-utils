# Reference: типы частей сессии opencode

Структура JSON после `opencode export <sessionID>`:

```json
{
  "info": { "id": "ses_…", "title": "…", "agent": "build", "model": {…}, "directory": "…", … },
  "messages": [
    {
      "info": { "role": "user" | "assistant", "id": "msg_…", "time": {…}, "agent": "build" },
      "parts": [ <Part>, … ]
    }
  ]
}
```

## Типы `parts` (opencode ≥ 1.17)

| `type` | Поля | Рендеринг в Markdown |
| --- | --- | --- |
| `text` | `text` | Плоский текст |
| `reasoning` | `text` | ` ``` ` блок |
| `file` | `filename`, `mime`, `url`, `source?` | `📎 attachment: \`<name>\` (<mime>)` |
| `tool` | `tool`, `state: { status, input, output, metadata, title, time }` | `🔧 tool: \`<name>\` — *<title>*` + JSON-аргументы и вывод |
| `agent` | `name`, `source?` | `🤖 sub-agent: <name>` |
| `subtask` | `prompt`, `description`, `command?` | `↳ subtask: <description>` |
| `patch` | `hash`, `files[]` | `🩹 patch — N file(s) — \`<hash>\`` + ` ```diff ` блоки |
| `snapshot` | `snapshot` | `📸 snapshot: \`<id>\`` |
| `step-start` | `snapshot?` | пусто (граница шага) |
| `step-finish` | `snapshot?`, `reason?` | пусто (граница шага) |

Полный источник истины — `packages/opencode/src/cli/cmd/export.ts` в репозитории `sst/opencode`.

## Sanitize

`opencode export --sanitize` заменяет чувствительные поля на плейсхолдеры
`[redacted:<kind>:<id>]` — в том числе весь `text`, имена файлов, заголовки
сессии и сообщений, директорию, входы/выходы tool-вызовов. После
`--sanitize` восстановить содержимое нельзя. Для Markdown-экспорта запускайте
`opencode export` **без** `--sanitize`.
