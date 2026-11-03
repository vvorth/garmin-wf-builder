// The SDK and the environment, from the server: the dialog that installs
// Garmin's SDK when none is found (shown on every load until one is), the
// Doctor dialog over `wfb doctor`'s report, and the SDK Manager's
// downloads. These talk to the server directly (`api/sdk`, `api/doctor`),
// not through the worker: they are about this computer, not a face.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useEffect, useState } from "preact/hooks";
import type { Agreement, DeviceInfo, DoctorReport, SdkStatus } from "../src/studio/protocol.ts";
import { Modal } from "./dialogs.ts";

/** The server's JSON at `path`, or the error it gave. */
async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(body.error || `${response.status}`);
  return body;
}

export const sdkStatus = (refresh = false): Promise<SdkStatus> => getJson<SdkStatus>(refresh ? "api/sdk?refresh=1" : "api/sdk");
export const doctorReport = (): Promise<DoctorReport> => getJson<DoctorReport>("api/doctor");

const mb = (bytes: number): string => `${(bytes / (1024 * 1024)).toFixed(0)} MB`;

/** The SDK Manager's download per OS, and Garmin's SDK page, as a short list. */
export function ManagerLinks({ status }: { status: SdkStatus }): VNode {
  const m = status.manager;
  return html`<div class="manager-links">
    <div>Garmin's Connect IQ SDK Manager downloads the SDK and, for a signed-in Garmin account, the
      definitions of the watches you build for, with Garmin's font files beside them. Downloading
      it accepts Garmin's Connect IQ Developer Agreement, on <a href=${m.page} target="_blank" rel="noopener">its SDK page</a>.</div>
    <ul class="choices">
      ${Object.keys(m.downloads).map((os) => html`<li><strong>${m.names[os]}</strong>
        <a href=${m.downloads[os]} target="_blank" rel="noopener">${m.downloads[os]!.split("/").pop()}</a>
        <div class="dim small">keeps its files under <code>${m.folders[os]}</code> (Sdks, Devices, Fonts)</div></li>`)}
    </ul>
    ${status.inContainer ? html`<div class="dim small">Mount those folders into the container: <code>Sdks</code> at <code>/sdk</code>,
      <code>Devices</code> at <code>/devices</code>, <code>Fonts</code> at <code>/fonts</code> (read-only). The devices cannot be
      downloaded by anything but the SDK Manager, signed in.</div>` : null}
  </div>`;
}

export function SdkManagerDialog({ status, onClose }: { status: SdkStatus; onClose: () => void }): VNode {
  return html`<${Modal} title="The SDK Manager" onClose=${onClose}>
    <div class="modal-body"><${ManagerLinks} status=${status} /></div>
    <div class="modal-foot"><button class="primary" onClick=${onClose}>Close</button></div>
  </${Modal}>`;
}

export interface SdkDialogProps {
  status: SdkStatus;
  /** Why it opened: no SDK at all, or a newer one to install. */
  reason: "missing" | "update";
  onClose: () => void;
}

/**
 * Install Garmin's SDK: the agreement to read and accept, the download
 * with its progress, and the reload that shows what it gave the devices.
 * Without a download possible here (a macOS or Windows host), the SDK
 * Manager's links instead.
 */
export function SdkDialog({ status: initial, reason, onClose }: SdkDialogProps): VNode {
  const [status, setStatus] = useState<SdkStatus>(initial);
  const [agreement, setAgreement] = useState<Agreement | null | "loading" | "unavailable">("loading");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const download = status.download;
  const busy = download !== null && (download.phase === "downloading" || download.phase === "unpacking");

  useEffect(() => {
    if (!status.canDownload) { setAgreement(null); return; }
    let live = true;
    getJson<Agreement>("api/sdk/agreement").then((a) => live && setAgreement(a), () => live && setAgreement("unavailable"));
    return () => { live = false; };
  }, [status.canDownload]);

  // While a download runs, the server is asked where it is, once a second.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => sdkStatus().then(setStatus, () => {}), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  const install = async (): Promise<void> => {
    setError(null);
    try {
      await getJson("api/sdk/download", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accept: true }) });
      setStatus(await sdkStatus());
    } catch (e) { setError(String((e as Error).message)); }
  };

  const title = reason === "update" ? `A newer SDK: ${status.newer?.version ?? ""}` : "The Connect IQ SDK is needed";
  const done = download !== null && download.phase === "done";
  return html`<${Modal} title=${title} onClose=${onClose} className="sdk">
    <div class="modal-body">
      ${reason === "missing" ? html`<div>No Connect IQ SDK was found on this computer${status.inContainer ? " (nothing is mounted at /sdk)" : ""}.
          The editor works without it, but <strong>Build</strong> needs Garmin's compiler, which the SDK holds.</div>`
        : html`<div>Garmin lists SDK <strong>${status.newer?.version}</strong>; installed is ${status.sdk?.version}.</div>`}
      ${status.canDownload ? html`
        <div>The SDK downloads from Garmin without a sign-in, into <code>${status.downloadFolder}</code>${status.inContainer ? " (mount a volume there, or at /cache, to keep it)" : ""}.
          Downloading it accepts Garmin's Connect IQ Developer Agreement, which licenses the SDK to you alone, for developing and testing:</div>
        ${agreement === "loading" ? html`<div class="dim">Fetching the agreement from Garmin's page…</div>` : null}
        ${agreement !== null && agreement !== "loading" && agreement !== "unavailable" ? html`
          <div class="dim small">${agreement.updated} · <a href=${agreement.url} target="_blank" rel="noopener">on Garmin's page</a></div>
          <pre class="agreement">${agreement.text}</pre>` : null}
        ${agreement === "unavailable" ? html`<div class="error-text">The agreement could not be read from Garmin's page just now;
          read it there: <a href=${status.manager.page} target="_blank" rel="noopener">${status.manager.page}</a>.</div>` : null}
        <label class="accept"><input type="checkbox" checked=${accepted} disabled=${busy || done}
            onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => setAccepted(e.currentTarget.checked)} />
          I have read and accept Garmin's Connect IQ Developer Agreement.</label>
        ${download !== null ? html`<div class="download">
          ${download.phase === "downloading" ? html`<div>Downloading${download.version ? ` SDK ${download.version}` : ""}…
              ${download.total ? `${mb(download.received)} of ${mb(download.total)}` : mb(download.received)}</div>
            <progress max=${download.total ?? 0} value=${download.total ? download.received : undefined}></progress>` : null}
          ${download.phase === "unpacking" ? html`<div>Unpacking…</div><progress></progress>` : null}
          ${download.phase === "done" ? html`<div class="ok-text">${download.message}.</div>
            <div>Reload the page: the editor then reads the watches with what the SDK knows about them.</div>` : null}
          ${download.phase === "failed" ? html`<div class="error-text">The download failed: ${download.message}</div>` : null}
        </div>` : null}
        ${error ? html`<div class="error-text">${error}</div>` : null}`
      : html`<div>On this computer the SDK Manager installs the SDK; the editor finds it where the SDK Manager puts it.</div>
        <${ManagerLinks} status=${status} />`}
    </div>
    <div class="modal-foot">
      ${done ? html`<button class="primary" onClick=${() => location.reload()}>Reload</button>`
        : html`<button onClick=${onClose}>${status.canDownload ? "Later" : "Close"}</button>
          ${status.canDownload ? html`<button class="primary" disabled=${!accepted || busy || agreement === "loading"} onClick=${install}>
            ${busy ? "Installing…" : `Download and install${status.newer && reason === "update" ? ` SDK ${status.newer.version}` : " the SDK"}`}</button>` : null}`}
    </div>
  </${Modal}>`;
}

const Mark = ({ ok }: { ok: boolean | "none" }): VNode => html`<span class=${"mark " + (ok === true ? "ok" : ok === "none" ? "none" : "missing")}>${ok === true ? "ok" : ok === "none" ? "none" : "MISSING"}</span>`;

/** A check's row: its mark, its name, what was found, and the hints beneath. */
function Row({ ok, name, children, hints = [] }: { ok: boolean | "none"; name: string; children?: unknown; hints?: string[] }): VNode {
  return html`<div class="doctor-row">
    <${Mark} ok=${ok} /><div class="doctor-name">${name}</div>
    <div class="doctor-detail">${children}${hints.length ? html`<div class="dim small hints">${hints.map((h) => html`<div>${h}</div>`)}</div>` : null}</div>
  </div>`;
}

export interface DoctorDialogProps {
  /** The watches the editor knows, for their names beside the ids. */
  devices: readonly Pick<DeviceInfo, "id" | "name">[];
  onClose: () => void;
  /** Open the SDK dialog for a newer SDK, or for the one missing. */
  onInstallSdk: (status: SdkStatus, reason: "missing" | "update") => void;
  onManagerLinks: (status: SdkStatus) => void;
}

/** `wfb doctor` in the editor: every check, the lists behind the counts, and the SDK's update. */
export function DoctorDialog({ devices, onClose, onInstallSdk, onManagerLinks }: DoctorDialogProps): VNode {
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [status, setStatus] = useState<SdkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const run = (refresh = false): void => {
    setError(null);
    setChecking(true);
    Promise.all([doctorReport(), sdkStatus(refresh)]).then(([r, s]) => { setReport(r); setStatus(s); }, (e: unknown) => setError(String((e as Error).message)))
      .finally(() => setChecking(false));
  };
  useEffect(() => { run(); }, []);
  const nameOf = (id: string): string => devices.find((d) => d.id === id)?.name ?? "";
  const r = report;
  return html`<${Modal} title="Doctor" onClose=${onClose} className="doctor">
    <div class="modal-body">
      ${error ? html`<div class="error-text">${error}</div>` : null}
      ${r === null && !error ? html`<div class="dim">Checking…</div>` : null}
      ${r !== null ? html`
        <div class=${"verdict " + r.verdict.replace(" ", "-")}>
          <strong>${r.verdict}</strong>${r.verdict === "ready" ? ": validate, preview and build all work."
            : r.verdict === "partial" ? ": validate and preview work; Build cannot compile yet." : ""}
          ${r.problems.length ? html`<div class="small">fix: ${r.problems.join("; ")}</div>` : null}
        </div>
        <${Row} ok=${r.node.problem === null} name="node" hints=${r.node.problem ? [r.node.problem] : []}>${r.node.version} <span class="dim small">${r.node.path}</span></${Row}>
        <${Row} ok=${r.schema.ok} name="schema"><span class="small">${r.schema.path}</span></${Row}>
        <${Row} ok=${r.reference.ok} name="device reference" hints=${r.reference.hints}>
          <span class="small">${r.reference.dir}</span>${r.reference.sdkVersion ? html` <span class="dim small">from SDK ${r.reference.sdkVersion}</span>` : null}</${Row}>
        <${Row} ok=${r.iconFont.ok} name="icon font" hints=${r.iconFont.ok ? [] : ["run tools/setup-env.sh, or node ts/tools/fetch-icon-font.ts"]}><span class="small">${r.iconFont.path}</span></${Row}>
        <${Row} ok=${r.garminFonts.root !== null ? true : "none"} name="Garmin fonts" hints=${r.garminFonts.hints}>
          ${r.garminFonts.root !== null ? html`<details><summary>${r.garminFonts.files.length} files at <span class="small">${r.garminFonts.root}</span></summary>
              <ul class="listing">${r.garminFonts.files.map((f) => html`<li><code>${f}</code></li>`)}</ul></details>`
            : html`not found <span class="dim">(optional: previews draw stand-in typefaces for any face the registry has no exact match for)</span>`}</${Row}>
        <${Row} ok=${r.devices.root !== null ? true : r.devices.hints.length === 0 ? "none" : false} name="devices" hints=${r.devices.hints}>
          ${r.devices.root !== null ? html`<details><summary>${r.devices.ids.length} installed at <span class="small">${r.devices.root}</span></summary>
              <ul class="listing">${r.devices.ids.map((id) => html`<li><code>${id}</code> <span class="dim">${nameOf(id)}</span></li>`)}</ul></details>`
            : r.devices.error}</${Row}>
        ${r.systemFonts !== null ? html`<${Row} ok=${r.systemFonts.lacking.length === 0 ? true : "none"} name="system fonts" hints=${r.systemFonts.hints}>
          ${r.systemFonts.lacking.length === 0 ? `all ${r.devices.ids.length} devices covered (${r.systemFonts.summary} font names)`
            : `${r.systemFonts.lacking.length} of ${r.devices.ids.length} devices lack a stand-in: ${r.systemFonts.lacking.join(", ")}`}</${Row}>` : null}
        <${Row} ok=${r.sdk !== null} name="Connect IQ SDK" hints=${r.sdk === null ? r.sdkHints : r.sdk.copied ? [`read-only, so the compiler runs from a copy at ${r.sdk.compiler}`] : []}>
          ${r.sdk !== null ? html`${r.sdk.version} <span class="dim small">${r.sdk.install}</span>` : null}
          ${r.newerSdk !== null ? html`<div class="newer">SDK ${r.newerSdk.version} is available.
              ${status?.canDownload ? html`<button onClick=${() => status && onInstallSdk(status, "update")}>Install SDK ${r.newerSdk.version}…</button>` : html`<span class="dim small">${r.newerSdk.how}</span>`}</div>` : null}
          ${r.sdk === null && status ? html`<div><button class="primary" onClick=${() => onInstallSdk(status, "missing")}>${status.canDownload ? "Install the SDK…" : "How to get the SDK…"}</button></div>` : null}
          ${r.referenceStale !== null ? html`<div class="error-text small">the device reference came from SDK ${r.referenceStale.extracted}</div>` : null}</${Row}>
        ${r.key !== null ? html`<${Row} ok=${r.key.state !== "missing"} name="developer key" hints=${r.key.hints}>
          ${r.key.state === "will-generate" ? "will be generated at " : r.key.state === "missing" ? "expected at " : ""}<span class="small">${r.key.path}</span></${Row}>` : null}` : null}
    </div>
    <div class="modal-foot">
      ${status ? html`<button onClick=${() => onManagerLinks(status)}>SDK Manager downloads…</button>` : null}
      <button disabled=${checking} onClick=${() => run(true)} title="Run the checks again, and ask Garmin for its newest SDK">${checking ? "Checking…" : "Check again"}</button>
      <button class="primary" onClick=${onClose}>Close</button>
    </div>
  </${Modal}>`;
}

/** Which of the environment's dialogs is open. */
type EnvDialog = { kind: "sdk"; status: SdkStatus; reason: "missing" | "update" } | { kind: "doctor" } | { kind: "manager"; status: SdkStatus } | null;

// The environment's dialogs are opened from the top bar and the home
// screen alike, so `EnvHost` (mounted once, by the app's shell) holds them,
// and `openDoctor()` reaches it from anywhere, as `ask()` reaches `AskHost`.
let opening: ((dialog: EnvDialog) => void) | null = null;
export function openDoctor(): void {
  opening?.({ kind: "doctor" });
}

/**
 * The environment's dialogs, and the SDK gate: on every load the page asks
 * the server for the SDK once it is up and opens the SDK dialog when none
 * is found; `Later` closes it for this load only.
 */
export function EnvHost({ devices }: { devices: readonly Pick<DeviceInfo, "id" | "name">[] }): VNode | null {
  const [dialog, setDialog] = useState<EnvDialog>(null);
  useEffect(() => { opening = setDialog; return () => { opening = null; }; }, []);
  useEffect(() => {
    let live = true;
    sdkStatus().then((s) => { if (live && s.sdk === null) setDialog({ kind: "sdk", status: s, reason: "missing" }); }, () => {});
    return () => { live = false; };
  }, []);
  if (dialog === null) return null;
  const close = (): void => setDialog(null);
  if (dialog.kind === "sdk") return html`<${SdkDialog} status=${dialog.status} reason=${dialog.reason} onClose=${close} />`;
  if (dialog.kind === "manager") return html`<${SdkManagerDialog} status=${dialog.status} onClose=${close} />`;
  return html`<${DoctorDialog} devices=${devices} onClose=${close}
    onInstallSdk=${(status: SdkStatus, reason: "missing" | "update") => setDialog({ kind: "sdk", status, reason })}
    onManagerLinks=${(status: SdkStatus) => setDialog({ kind: "manager", status })} />`;
}
