"use client";

import { useEffect, useRef, useState } from "react";

export default function PdfDownload({
  projectId,
  kind,
  resultId,
  savedAt,
  version,
  disabled,
}: {
  projectId: string;
  kind: "snapshot" | "comparison";
  resultId: string;
  savedAt: string;
  version: string;
  disabled: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const active = useRef<AbortController | null>(null);
  const url = useRef<string | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
      if (url.current) URL.revokeObjectURL(url.current);
    },
    [resultId],
  );

  async function download() {
    if (busy || disabled) return;
    const controller = new AbortController();
    active.current?.abort();
    active.current = controller;
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(120_000),
    ]);
    setBusy(true);
    setDone(false);
    setError("");
    try {
      const ticketResponse = await fetch(
        `/api/guest/projects/${projectId}/exports`,
        {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind, result_id: resultId }),
          signal,
        },
      );
      const ticket = await ticketResponse.json();
      if (!ticketResponse.ok)
        throw new Error(
          ticket.detail ?? "Unable to prepare this saved report.",
        );
      // Binary content bypasses Vercel. No credential goes in a URL or filename.
      const response = await fetch(ticket.transfer_url, {
        headers: { Authorization: `Bearer ${ticket.token}` },
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        signal,
      });
      if (!response.ok) {
        const failure = await response.json();
        throw new Error(
          failure.detail ?? "Unable to download this saved report.",
        );
      }
      if (!response.headers.get("content-type")?.includes("application/pdf"))
        throw new Error("The service did not return a PDF. Please retry.");
      const blob = await response.blob();
      if (signal.aborted || active.current !== controller) return;
      if (url.current) URL.revokeObjectURL(url.current);
      url.current = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url.current;
      anchor.download = `renotrace-${kind}-${resultId}.pdf`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setDone(true);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          (e as Error).name === "TimeoutError"
            ? "PDF preparation timed out. Please retry; a fresh ticket will be requested."
            : (e as Error).message,
        );
    } finally {
      if (!controller.signal.aborted && active.current === controller)
        setBusy(false);
    }
  }

  return (
    <section className="pdf-export" aria-label="Download selected saved report">
      <h4>
        Download this saved {kind === "comparison" ? "recheck" : "calculation"}
      </h4>
      <p>
        Selected version: {version} · saved {new Date(savedAt).toLocaleString()}
      </p>
      <p className="pdf-version">Report reference: {resultId}</p>
      <p>
        This historical PDF uses only the selected saved result. Drafts, unsaved
        choices and later replies are not included. Save a new review to include
        new information. Unknown values and unresolved questions remain visible.
      </p>
      <p>
        The PDF contains reconciliation and source references, without the
        original files. Your downloaded copy remains on your device after the
        24-hour guest access expires.
      </p>
      <button disabled={disabled || busy} onClick={() => void download()}>
        {kind === "comparison"
          ? "Download recheck PDF"
          : "Download calculation PDF"}
      </button>
      {busy && <p role="status">Preparing the PDF from saved evidence…</p>}
      {done && (
        <p role="status">
          PDF download started. No case data or access period changed.
        </p>
      )}
      {error && <p role="alert">{error} Use the download button to retry.</p>}
    </section>
  );
}
