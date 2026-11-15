// Spec 021 FR-2: public pages /privacy and /consent. The text comes from the API (data with a version).
import { useQuery } from "@tanstack/react-query";
import { Fragment } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { errorMessage, t } from "../../shared/i18n";
import { ApiError } from "../../shared/api/client";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { legalDocument, type LegalKind } from "./api";
import "./legal.css";

// A web address in the text becomes a link (the text is data: it carries the address, not the markup).
const URL_RE = /(https?:\/\/[^\s)]+)/g;

function Paragraph({ text }: { text: string }) {
  return (
    <p>
      {text.split(URL_RE).map((part, i) =>
        i % 2 === 1 ? (
          <a key={i} href={part} target="_blank" rel="noopener noreferrer">
            {part}
          </a>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </p>
  );
}

// «2026-11-15» -> «15.11.2026»
function versionDate(version: string): string {
  const [y, m, d] = version.split("-");
  return `${d}.${m}.${y}`;
}

export function LegalPage({ kind }: { kind: LegalKind }) {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["legal", "document", kind],
    queryFn: () => legalDocument(kind),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const doc = query.data;
  // The feature is off (404 feature_disabled): the pages are not available, the way out is the login page.
  if (query.error instanceof ApiError && query.error.code === "feature_disabled") {
    return <Navigate to="/login" replace />;
  }
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
                <Paragraph key={i} text={text} />
              ))}
            </section>
          ))}
        </>
      ) : null}
      <p className="legal-footer">
        {/* «Назад» — на прежний экран (форма, с которой открыли в той же вкладке); без истории — ко входу. */}
        <button
          type="button"
          className="legal-back"
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/login"))}
        >
          {t("legal.back")}
        </button>
        <Link to="/login">{t("legal.to_login")}</Link>
      </p>
    </article>
  );
}
