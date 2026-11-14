// Spec 021 FR-2: public pages /privacy and /consent. The text comes from the API (data with a version).
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { errorMessage, t } from "../../shared/i18n";
import { ApiError } from "../../shared/api/client";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { legalDocument, type LegalKind } from "./api";
import "./legal.css";

// «2026-11-15» -> «15.11.2026»
function versionDate(version: string): string {
  const [y, m, d] = version.split("-");
  return `${d}.${m}.${y}`;
}

export function LegalPage({ kind }: { kind: LegalKind }) {
  const query = useQuery({
    queryKey: ["legal", "document", kind],
    queryFn: () => legalDocument(kind),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const doc = query.data;
  return (
    <article className="legal-page">
      {query.isPending ? <p role="status">{t("app.loading")}</p> : null}
      {query.isError ? (
        <ErrorAlert message={errorMessage(query.error instanceof ApiError ? query.error.code : "unknown")} />
      ) : null}
      {doc !== undefined ? (
        <>
          <h1>{doc.title}</h1>
          <p className="legal-version">{t("legal.version", { date: versionDate(doc.version) })}</p>
          {doc.sections.map((section, index) => (
            <section key={index}>
              {section.heading !== null ? <h2>{section.heading}</h2> : null}
              {section.paragraphs.map((text, i) => (
                <p key={i}>{text}</p>
              ))}
            </section>
          ))}
        </>
      ) : null}
      <p className="legal-footer">
        <Link to="/login">{t("legal.to_login")}</Link>
      </p>
    </article>
  );
}
