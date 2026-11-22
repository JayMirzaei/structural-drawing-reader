"""Streamlit UI: load a drawing set, ask questions, see the evidence on the sheet.

Run:  uv run streamlit run app/streamlit_app.py

Settings come from the environment and from `.env` in the repository root (read first, before any
setting is used; variables already set win). Drawing text and model answers are shown with Markdown
escaped, so text on a drawing can never turn into a link or an image in the page.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path

import streamlit as st

from drawing_reader import ocr, settings

ROOT = Path(__file__).resolve().parents[1]
# git-ignored; may hold API keys and DRAWING_READER_* settings. DRAWING_READER_ENV_FILE points elsewhere (the tests
# point it at an empty folder, so a developer's own .env cannot change their results).
settings.load_env_file(os.environ.get("DRAWING_READER_ENV_FILE") or ROOT / ".env")

from drawing_reader.ingest import UnreadablePDF, ingest  # noqa: E402  (after .env, by intent)
from drawing_reader.parse import build_index  # noqa: E402
from drawing_reader.providers import PROVIDERS, ProviderInfo, create_provider  # noqa: E402
from drawing_reader.qa import (  # noqa: E402
    KIND_COLORS,
    answer,
    escape_markdown,
    first_look,
    render_sheet,
    safe_markdown,
    scope_advice,
    text_layer_notice,
)
from drawing_reader.schema import Index  # noqa: E402

CACHE = settings.cache_dir(ROOT / ".drawing_reader_cache")
UPLOADS = CACHE / "uploads"
# The vector set first: it is the default, and it needs nothing beyond `uv sync`.
EXAMPLE_ORDER = ("access_platform_set.pdf", "access_platform_scan.pdf")
EXAMPLES = sorted(
    (ROOT / "examples").glob("*.pdf"),
    key=lambda p: (EXAMPLE_ORDER.index(p.name) if p.name in EXAMPLE_ORDER else len(EXAMPLE_ORDER), p.name),
)
RULES_ONLY = "Rules only (no LLM)"
UPLOAD_NAME_CHARS = 60  # an uploaded file is saved as <hash>_<name>; long names are cut to stay valid on disk

st.set_page_config(page_title="Structural Drawing Reader", layout="wide")


def server_key(info: ProviderInfo) -> str:
    """A key provided by whoever runs the app: Streamlit secrets, the environment or the .env file."""
    try:
        for name in info.key_env:
            if name in st.secrets:
                return str(st.secrets[name])
    except Exception:  # noqa: BLE001  no secrets file at all is the normal local case
        pass
    return info.key_from_env()


@st.cache_data(show_spinner="Reading the drawing set…")
def build(pdf_path: str, mtime: float) -> str:
    """Ingest and parse; returns the path of the saved index JSON (cached on path and mtime)."""
    doc = ingest(pdf_path, CACHE)
    idx = build_index(doc)
    out = CACHE / doc.doc_id / "index.json"
    idx.save(out)
    return str(out)


def load_index(pdf_path: Path) -> Index:
    """The fact index of the PDF; an unreadable file stops the page with a message saying why."""
    try:
        return Index.load(build(str(pdf_path), pdf_path.stat().st_mtime))
    except UnreadablePDF as error:
        st.session_state.pop("pdf_path", None)
        st.error(f"This file cannot be read as a drawing set. {error}")
        st.stop()
        raise  # st.stop() ends the script run; this line is never reached


def example_label(path: Path) -> str:
    label = path.stem.replace("_", " ")
    if "scan" in path.stem and not ocr.available():
        label += " (needs the ocr extra)"
    return label


def save_upload(up) -> Path:
    data = up.getvalue()
    UPLOADS.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(up.name).stem)[:UPLOAD_NAME_CHARS]
    p = UPLOADS / f"{hashlib.sha1(data).hexdigest()[:12]}_{stem}.pdf"
    if not p.exists():
        p.write_bytes(data)
    return p


def provider_settings() -> dict:
    """The provider picker. Returns {"name", "api_key", "model", "base_url"}; name "none" = rules only.

    The first choice is DRAWING_READER_PROVIDER when it is set. A key typed here stays in this browser
    session's memory. It is never written to disk, shown back or logged."""
    st.subheader("LLM (optional)")
    titles = {RULES_ONLY: "none"} | {info.title: name for name, info in PROVIDERS.items()}
    names = list(titles.values())
    configured = settings.provider_name()
    choice = st.radio(
        "When rules are unsure, ask…",
        list(titles),
        index=names.index(configured) if configured in names else 0,
        help="Rules answer first. The LLM is only asked when no rule is confident, and it may only cite "
        "facts that exist in the index. A local model never sends drawings anywhere.",
    )
    chosen = {"name": titles[choice], "api_key": "", "model": "", "base_url": ""}
    if chosen["name"] == "none":
        return chosen
    info = PROVIDERS[chosen["name"]]
    if not info.sdk_installed():
        st.warning(f"The `{info.sdk}` package is not installed. Install it with `uv sync --extra {info.extra}`.")
    if info.needs_key:
        key = server_key(info)
        if key:
            st.write("API key: provided by the server")
        else:
            key = st.text_input(
                f"{info.title} API key",
                type="password",
                placeholder="paste key here (kept in memory only)",
                help=f"Or set {' / '.join(info.key_env)} in the environment or in a .env file before starting the app.",
            ).strip()
            st.write("API key: " + ("set" if key else "not set, so answers come from rules only"))
        chosen["api_key"] = key
        chosen["model"] = st.text_input("Model", value=info.default_model()).strip()
    else:
        chosen["base_url"] = st.text_input(
            "Server URL",
            value=settings.local_url(),
            help="An OpenAI-compatible server: llama.cpp `llama-server` or Ollama.",
        ).strip()
        if st.button("Clear cached answers", help="Forget cached local answers for the loaded document."):
            st.session_state["clear_llm_cache"] = True
    return chosen


def provider_for(chosen: dict, idx: Index):
    """The provider for the current settings and document, rebuilt only when one of them changes."""
    if chosen["name"] == "none":
        return None
    signature = (chosen["name"], idx.doc_id, chosen["model"], chosen["api_key"], chosen["base_url"])
    if st.session_state.get("llm_signature") != signature:
        provider = create_provider(
            chosen["name"],
            CACHE / idx.doc_id,
            api_key=chosen["api_key"] or None,
            model=chosen["model"] or None,
            base_url=chosen["base_url"] or None,
        )
        st.session_state["llm"], st.session_state["llm_signature"] = provider, signature
        if chosen["name"] == "local" and provider.enabled:
            # Warm the server's prompt cache for the two sheets most questions land on (the ones with
            # the most facts), in the background, so the first real question is not a cold start.
            counts = {n: sum(1 for f in idx.facts if f.sheet == n) for n in idx.sheet_numbers()}
            likely = sorted(counts, key=counts.get, reverse=True)[:2]
            threading.Thread(target=provider.prewarm, args=(idx, likely), daemon=True).start()
    return st.session_state["llm"]


# ---- sidebar ------------------------------------------------------------------------------------
with st.sidebar:
    st.title("Structural Drawing Reader")
    st.caption("Reads a structural drawing PDF, indexes what is on it, answers questions with evidence.")
    up = st.file_uploader("Drawing set (PDF)", type=["pdf"])
    example = None
    if EXAMPLES:
        example = st.selectbox("Example set", EXAMPLES, format_func=example_label)
    use_example = st.button("Load the example", disabled=not EXAMPLES)
    st.divider()
    chosen_provider = provider_settings()
    st.divider()
    kinds = st.multiselect(
        "Overlay fact kinds", options=sorted(KIND_COLORS), default=["label", "elevation", "callout", "grid"]
    )
    if st.button("Clear cache & rebuild"):
        st.cache_data.clear()
        st.rerun()

# ---- choose the document ------------------------------------------------------------------------
pdf_path: Path | None = None
if up is not None:
    pdf_path = save_upload(up)
elif use_example and example is not None:
    pdf_path = example
elif st.session_state.get("pdf_path"):
    pdf_path = Path(st.session_state["pdf_path"])

if pdf_path is None:
    st.header("Load a drawing set to begin")
    st.write(
        "Upload a PDF in the sidebar, or load an example. Vector PDFs (exported from CAD or BIM software) are read "
        "directly. Scanned PDFs are read by OCR when the `ocr` extra is installed; expect less from them."
    )
    st.stop()

idx = load_index(pdf_path)
if st.session_state.get("pdf_path") != str(pdf_path) or "history" not in st.session_state:
    st.session_state["pdf_path"] = str(pdf_path)
    st.session_state["history"] = []
    st.session_state["highlight"] = []
    st.session_state["sheet"] = None

provider = provider_for(chosen_provider, idx)
if provider is not None and st.session_state.pop("clear_llm_cache", False):
    st.sidebar.success(f"Cleared {provider.clear_cache()} cached answer(s).")
if provider is not None and not provider.enabled:
    st.sidebar.warning(f"LLM not available: {provider.last_error}. Answers come from rules only.")
llm = provider if provider is not None and provider.enabled else None
max_calls = settings.max_llm_calls()
llm_calls = st.session_state.setdefault("llm_calls", 0)  # every attempt this session, whichever provider
if llm is not None and llm_calls >= max_calls:
    st.sidebar.warning(f"LLM call limit for this session reached ({max_calls}); answers continue with rules only.")
    llm = None

# ---- main area ----------------------------------------------------------------------------------
left, right = st.columns([1.35, 1])

with right:
    st.subheader("Ask the drawing")
    with st.expander("First look: what the reader found", expanded=not st.session_state.get("history")):
        st.markdown(safe_markdown(first_look(idx)))
    if idx.from_ocr:
        st.info(
            "This PDF is a scan. Text was read by OCR, so spelling and numbers can be wrong: check answers against "
            "the highlighted sheet. Circles (grid bubbles, elevation markers) are not read from scans."
        )
    elif notice := text_layer_notice(idx):
        st.warning(notice)
    for notice in scope_advice(idx):
        st.warning(notice)

    chat_box = st.container(height=520)
    for i, (role, content, meta) in enumerate(st.session_state.get("history", [])):
        with chat_box.chat_message(role):
            st.markdown(safe_markdown(content) if role == "assistant" else escape_markdown(content))
            if meta:
                sheets = f" · sheets {', '.join(meta['sheets'])}" if meta["sheets"] else ""
                st.caption(escape_markdown(f"{meta['method']} · confidence {meta['confidence']:.2f}{sheets}"))
                for c in meta.get("caveats", []):
                    st.caption("Caveat: " + escape_markdown(c))
                if meta["fact_ids"] and meta["sheets"]:
                    cols = st.columns(min(4, len(meta["sheets"])))
                    for j, sh in enumerate(meta["sheets"]):
                        if cols[j % len(cols)].button(f"Show on {sh}", key=f"ev_{i}_{sh}"):
                            st.session_state["sheet"] = sh
                            st.session_state["highlight"] = meta["fact_ids"]
                            st.rerun()

    q = st.chat_input("e.g. What are the brace sections?  Which sheets are missing?  Base plate thickness?")
    if q:
        before = llm.calls if llm is not None else 0
        a = answer(q, idx, llm=llm)
        st.session_state["llm_calls"] += (llm.calls - before) if llm is not None else 0
        meta = {
            "method": a.method,
            "confidence": a.confidence,
            "sheets": a.sheets,
            "fact_ids": a.fact_ids,
            "caveats": a.caveats,
        }
        st.session_state["history"].append(("user", q, None))
        st.session_state["history"].append(("assistant", a.text, meta))
        st.session_state["highlight"] = a.fact_ids
        if a.sheets:
            st.session_state["sheet"] = a.sheets[0]
        st.rerun()

with left:
    numbers = idx.sheet_numbers()
    cur = st.session_state.get("sheet") or numbers[0]
    if cur not in numbers:
        cur = numbers[0]
    sel = st.selectbox(
        "Sheet", numbers, index=numbers.index(cur), format_func=lambda n: f"{n} — {idx.sheet_by_number(n).title}"
    )
    if sel != st.session_state.get("sheet"):
        st.session_state["sheet"] = sel
    hl = st.session_state.get("highlight", [])
    img = render_sheet(idx, sel, set(kinds), hl)
    if img is not None:
        overlays = ", ".join(kinds) or "no overlays"
        st.image(
            img,
            width="stretch",
            caption=f"{sel}: red boxes = evidence for the last answer; thin boxes = {overlays}",
        )
    n_hl = sum(1 for f in idx.facts if f.id in set(hl) and f.sheet == sel)
    if hl:
        st.caption(f"{n_hl} evidence item(s) highlighted on this sheet · {len(hl)} total for the last answer")

    on_sheet = [f for f in idx.facts if f.sheet == sel]
    with st.expander(f"Facts on {sel} ({len(on_sheet)})"):
        kind_filter = st.multiselect("Kinds", sorted({f.kind for f in on_sheet}), default=[], key="factkinds")
        rows = [
            {
                "id": f.id,
                "kind": f.kind,
                "value": f.value,
                "unit": f.unit or "",
                "view": f.view or "",
                "conf": f.confidence,
                "source": f.source_text[:80],
            }
            for f in on_sheet
            if not kind_filter or f.kind in kind_filter
        ]
        st.dataframe(rows, width="stretch", height=300)

footer = f"doc {idx.doc_id} · {len(idx.facts)} facts"
if provider is not None:
    footer += f" · LLM calls this session: {st.session_state['llm_calls']}"
    if provider.last_error:
        footer += " · last LLM error: " + escape_markdown(provider.last_error)
st.caption(footer)
