// Метка «ИИ» + имя MCP-клиента (спека 022). Не кнопка; текст несёт смысл без цвета.
import { t } from "../i18n";

export function AgentMark({ name }: { name: string | null | undefined }) {
  if (!name) return null;
  return (
    <span className="ui-badge ui-badge--accent" data-role="ai-mark">
      {t("tasks.ai_mark")} {name}
    </span>
  );
}
