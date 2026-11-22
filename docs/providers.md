# Model providers

A provider is the optional second opinion. The rules answer first; a provider is asked only when
the best rule answer is below the confidence threshold (0.75). With no provider the reader works on
its rules alone and nothing leaves the machine.

## What a provider is allowed to do

A provider interprets; it never measures. It receives facts that were already extracted, with
their ids, and must answer in a fixed JSON shape (`LLMAnswer`):

```json
{
  "answer": "The brace is L102X102X9.5 (S-201, ELEVATION ON GRID 1).",
  "cited_fact_ids": ["S-201.label.009"],
  "sheets_used": ["S-201"],
  "confidence": 0.8,
  "caveats": []
}
```

Two checks run on every reply, whatever the provider (`providers/base.py: to_answer`):

- **Citations must exist.** A cited id that is not in the index is dropped and the drop is
  reported as a caveat. An answer with no surviving citation is capped at confidence 0.6 and marked
  unverified.
- **Numbers must be backed.** Every number in the answer text must occur in one of the cited facts
  (value, unit, view, source text or attributes). The set's own sheet numbers and fact ids are
  ignored; anything else that only looks like a reference (a bolt size "M24", a grade "A490") is
  checked like any other number. An unsupported number is named in a caveat and the answer is capped
  at 0.5.

Because the answer cites fact ids, the evidence boxes for a model's answer are drawn exactly as for
a rule's answer.

A failed call (network, quota, refusal, reply cut short, malformed JSON) returns an answer with
method `llm:error`. The router then keeps the best rule answer and adds the failure as a caveat; an
API key is removed from any error text before it is shown.

## Drawing text is data, not instructions

Everything taken from a drawing is untrusted: a note can contain anything, including text written to
look like an instruction to a model or Markdown that a browser would fetch. So:

- In the prompt, the fact index is inside `<fact_index> ... </fact_index>` and each sheet's text
  inside `<sheet_text sheet="..."> ... </sheet_text>`. A copy of those tags inside the drawing text
  is defused, so a note cannot close the block early. The system prompt says that everything inside
  the blocks, and everything in a sheet image, is data copied from the drawing, not instructions,
  and asks for plain text without links, images or HTML.
- In the app, answers (from rules or a model), the first look and caveats are shown with Markdown
  escaped (`qa/markdown.py`): only our own scaffolding (list bullets, a bold label) stays Markdown,
  so drawing text cannot become a link or an image in the page.

## What the model sees

| | Hosted providers (Gemini, OpenAI, Anthropic) | Local provider |
|---|---|---|
| Facts | the whole index, one JSON line per fact | the facts on the two most relevant sheets, in fixed id order, within a character budget (`DRAWING_READER_LOCAL_FACT_BUDGET`, default 9000) |
| Hints | ids of the top rule answers' facts | the same facts quoted in full next to the question |
| Sheet text | the two most relevant sheets | the same, cut to 4000 characters each |
| Images | the two sheets as JPEG, 1600 px wide | only when the server reports a vision model, 1024 px |
| Output | JSON schema enforced by the API | JSON schema enforced by the server |

"Most relevant" is a word-overlap score between the question and each sheet's text, with a strong
bonus for a word in the sheet title and a sheet named in the question.

The local provider sends less because a small model has a small context window. The fixed fact order
keeps the prompt prefix identical across questions about the same sheets, so the server's prompt
cache makes follow-up questions much faster. The app also warms that cache in the background when a
document is loaded.

## Caching

Each provider caches replies on disk under the document's cache folder, one file per (model,
document, question, sheets). A repeated question costs nothing; a changed PDF is a new document.
The app has a "Clear cached answers" button for the local provider, where a new model under the
same server is common.

## The providers

| Name | Extra | Key | Default model | Notes |
|---|---|---|---|---|
| `none` | | | | rules only (the default) |
| `local` | none | none | what the server has loaded | `DRAWING_READER_LOCAL_URL` (default `http://127.0.0.1:8080`); llama.cpp `/props` is probed first, then `/v1/models` |
| `gemini` | `gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3.8-flash` | `google-genai` SDK, `response_schema` |
| `openai` | `openai` | `OPENAI_API_KEY` | `gpt-5.4-mini` | Chat Completions with a strict `json_schema` response format |
| `anthropic` | `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` | Messages API with `output_config.format`; the fact index carries a prompt-cache breakpoint |

Each default model can be changed with `DRAWING_READER_<NAME>_MODEL` or in the app's sidebar. The
Anthropic provider can opt in to the API's server-side refusal fallback (a beta feature) with
`DRAWING_READER_ANTHROPIC_FALLBACKS=1`; it is off by default.

**How they are tested.** OpenAI and Anthropic through their real SDKs with a mocked HTTP transport
(request shape, parsing, refusal, cut-off reply, rejected key); Gemini through a recording client;
the local provider against a fake server (llama.cpp and Ollama-style probes, payload, failures).
**None of the four has been run against a live API or server for this release** (no keys were
available), so whether each service accepts the request as sent is not verified. The default model
ids in particular should be checked; override them with the variables above.

## Choosing one

```sh
# command line
uv sync --extra anthropic
export ANTHROPIC_API_KEY=...
uv run drawing-reader ask examples/access_platform_set.pdf "What bolts are used?" --provider anthropic

# a local server, nothing leaves the machine
llama-server -m model.gguf --port 8080          # or: ollama serve, then
export DRAWING_READER_LOCAL_URL=http://127.0.0.1:11434   # for Ollama
uv run drawing-reader ask examples/access_platform_set.pdf "What bolts are used?" --provider local
```

In the app, pick the provider in the sidebar; it starts on `DRAWING_READER_PROVIDER` when that is
set. A key typed there stays in the browser session's memory: it is never written to disk, shown
back or logged. Whoever runs the app can instead give keys through the environment, a `.env` file
in the repository root (read before any setting, without overriding the environment) or Streamlit
secrets (`.streamlit/secrets.toml.example`), and the sidebar then says the key is provided by the
server. The app limits model calls per browser session (`DRAWING_READER_MAX_LLM_CALLS`, default 40);
every attempt counts, failed ones included, and the count survives a change of provider or model.

All `DRAWING_READER_*` settings are read by `drawing_reader/settings.py` when they are used, never
frozen at import.

## Adding a provider

1. Create `src/drawing_reader/providers/<name>.py` with a subclass of `BaseProvider`:

   ```python
   DEFAULT_MODEL = "<model id>"  # DRAWING_READER_<NAME>_MODEL overrides it


   class NameProvider(BaseProvider):
       name = "<name>"
       cache_subdir = "llm_<name>"

       def __init__(self, cache_dir, model=None, api_key=None):
           # the registry reads the key from the provider's key variables and passes it in
           super().__init__(cache_dir, model or settings.model_for(self.name, DEFAULT_MODEL), api_key)
           self.enabled = bool(api_key)

       def _complete(self, question, idx, sheets, hint_ids) -> str:
           prompt = full_prompt(question, idx, sheets, hint_ids)  # or budgeted_prompt_text(...)
           # send SYSTEM_PROMPT + prompt to the API, constrained to strict_json_schema()
           # raise ProviderError on a refusal or a reply cut short
           return reply_json_text
   ```

   `_complete` only builds the request and returns the raw JSON. Caching, validation, the citation
   and number checks, and error handling are inherited from `BaseProvider.ask`. Import the SDK
   inside the method, so the package works without it. Optionally override `failure_text` to turn
   the SDK's exceptions into a plain message.
2. Register it in `PROVIDERS` in `providers/registry.py` (title, module, class, key variables, SDK
   import name, extra). The CLI's `--provider` choices and the app's picker come from there.
3. Add the SDK as an optional extra in `pyproject.toml` (and to the `dev` group, so its tests run on
   a plain `uv sync`).
4. Test it with a mocked transport or client, as `tests/test_provider_openai.py` does: the request
   shape, a valid reply, a refusal, a cut-off reply, a rejected key (and that the key is not in the
   error text). No test may touch the network.
