# A spoken phrase is turned into a config delta by the language model

**Priority: `LOW`** — off entirely without an API key and a network, and the one path here that costs seconds and money. [What the priorities mean](../how-to-write-scenario-docs.md).

Somebody says `ask something calmer`. No table can answer that — there is no
list of phrasings on which "calmer" is a colour scheme — so it costs a network
round trip, about two and a half seconds, and roughly four hundred tokens, and
comes back as `{"scheme": "navy"}`. The value is that a request nobody
anticipated still lands as an ordinary settings change: by the time the render
loop sees it, it is a dict indistinguishable from a line somebody typed, and it
is judged by the same validator in the same words.

This is the path taken only when
[`look_up`](../../src/language/shortcuts.py#L246) has already declined. That
ordering is the design: the table is exact and the model is fuzzy, so the table
is asked first and **before the API key is even looked for**, and what reaches
here is only what a table could not answer without guessing. A table that
guessed would compete with the model at the thing the model is for, and lose
quietly — a near miss becomes a wrong setting with no round trip to blame it
on. So `something calmer` is deliberately absent from the 137 phrasings, and
arrives here instead.

Two things are spent that the table costs nothing for, and both are visible in
the document below. The first is **time**, which on a 240x320 panel with no
spinner is indistinguishable from a camera that ignored you — so this is the
one path in the app that announces itself before doing its work, and the only
one whose diagram crosses a thread boundary. The second is **evidence**:
[`AskLog`](../../src/language/asklog.py#L75) records `source="model"` with the
elapsed seconds and the token usage, which is what makes the entry a fact about
the prompt. A table hit says nothing about the prompt, because the model was
never asked.

| Class | What it represents, and its part in this scenario |
|---|---|
| [`AskResolver`](../../src/language/resolver.py#L33) | The whole of the ask path, and the one part of the app allowed to be slow. Here it is the **escort**: [`resolve`](../../src/language/resolver.py#L98) finds the table has declined, confirms there is a key, says so on every display this run has, and hands the words to the parser. It never touches a setting itself |
| [`parser`](../../src/language/parser.py) | A module of functions rather than a class. Here it is the **translator**: [`parse`](../../src/language/parser.py#L401) builds a prompt whose tool schema is generated from [`SPECS`](../../src/control/render_config.py#L74), calls the model, and turns whichever tool came back into a `Parsed`. It is the only code in the app that knows a model exists |
| [`Parsed`](../../src/language/parser.py#L274) | What one utterance came back as. Here it is the **answer**, and a deliberately narrow one: exactly one of `delta` and `declined` is set, so nothing downstream has a third shape to handle. `unmet` rides alongside a delta and is not a refusal |
| [`RenderConfig`](../../src/control/render_config.py#L118) | The complete live render state, frozen so that it is replaced rather than mutated. Here it is the **briefing**: [`_describe`](../../src/language/parser.py#L396) turns it into the JSON the model is shown, which is the only reason "calmer" and "undo that" can mean anything. Read on this path, never written |
| [`MainRenderLooper`](../../ascii_camera.py#L98) | The one object the process is hung off, and the only thread a setting may be changed on. Here it is the **announcer**, and nothing else: [`_note`](../../ascii_camera.py#L337) is handed to the resolver as a callable so a slow request can say so on the panel and the status line without the resolver knowing either exists |
| [`AskLog`](../../src/language/asklog.py#L75) | An append-only record of every ask. Here it is the **receipt**: [`record`](../../src/language/asklog.py#L90) keeps the seconds and the token usage as well as the delta, so the cost of this path can be counted rather than estimated |

## A phrase no table could answer

```mermaid
sequenceDiagram
    autonumber
    actor Asker as whoever asked<br/>the CLI or the phone page
    participant App as AskResolver<br/>on the client's thread
    participant Cfg as RenderConfig<br/>frozen, read here not changed
    participant P as parser<br/>module of functions
    participant M as the model<br/>over the network
    participant Log as AskLog<br/>append-only
    participant Looper as MainRenderLooper<br/>render loop thread

    rect rgba(128, 128, 128, 0.12)
        note over Asker, Log: the client's own thread - may block for seconds
        Asker->>App: ask something calmer
        App->>Cfg: the settings callable gives config and previous
        Cfg-->>App: two frozen configs, neither half-applied
        App->>App: look_up declines, so the model is next
        App->>P: api_key finds a key, so ask is on
    end
    rect rgba(80, 140, 220, 0.12)
        note over Looper: the render loop's thread - must never block
        App->>Looper: _note "asking: something calmer" for TIMEOUT_SECONDS + 2
    end
    rect rgba(128, 128, 128, 0.12)
        note over Asker, Log: still the client's thread, for two and a half seconds
        App->>P: parse(utterance, config, previous)
        P->>P: _describe turns both configs into JSON
        P->>M: SYSTEM_PROMPT and tools() cached, settings and request after
        M-->>P: tool_use set_render, scheme navy
        P-->>App: Parsed(delta, unmet=None, seconds=2.6)
        App->>Log: record(source="model", seconds, usage)
        App-->>Asker: Ask(utterance, delta, note="2.6s")
    end
```

| Step | Message | What is going on |
|---:|---|---|
| 1 | `ask something calmer` | The `ask` prefix is the whole of the syntax, and everything after it is the utterance. Nothing here distinguishes a phrase the table knows from one it does not — that is discovered further down, which is why both scenarios share an entrance |
| 2 | the settings callable gives config and previous | [`AskResolver`](../../src/language/resolver.py#L33) is handed a callable rather than the values, because an ask arrives whenever somebody types one and is about the settings as they are at that moment |
| 3 | two frozen configs, neither half-applied | `previous` is the config before the last change, and it is what makes `undo that` answerable at all. It is `None` on the first change of a run, which is honest — there is nothing to undo yet |
| 4 | [`look_up`](../../src/language/shortcuts.py#L246) declines, so the model is next | An exact lookup over 137 phrasings, or `None`. `something calmer` is deliberately not among them: a table cannot decline well, it can only fail to match, and the two are not the same thing. **This step is the entire entry condition for this document** |
| 5 | [`api_key`](../../src/language/parser.py#L301) finds a key, so ask is on | Checked *after* the table and not before it, which is the whole reason a table hit survives a dead network and a missing key. With no key this returns a [`Reply`](../../src/control/command_server.py#L74) naming [`KEY_FILE`](../../src/language/parser.py#L101) and saying every other command still works — an answer, not a crash |
| 6 | [`_note`](../../ascii_camera.py#L337) "asking: something calmer" for [`TIMEOUT_SECONDS`](../../src/language/parser.py#L95) + 2 | The only step that crosses a thread. Two seconds of silence on a panel with no spinner is indistinguishable from a camera that ignored you, so the request announces itself before making it. The `+ 2` matters: the notice must outlive the parser's own timeout, or the panel goes quiet while the request is still out. A fixed four seconds was wrong for exactly this — a request may run for twenty |
| 7 | [`parse`](../../src/language/parser.py#L401)`(utterance, config, previous)` | The config is passed *in* rather than read here, so relative requests resolve against real values. A parse that raced a keypress resolves against settings one change stale, which for "something calmer" is not worth a lock |
| 8 | [`_describe`](../../src/language/parser.py#L396) turns both configs into JSON | Becomes `now` and, when `previous` is not `None`, `before`. This is the only reason the model can answer a comparative at all — "calmer" is meaningless without knowing what it is calmer *than* |
| 9 | [`SYSTEM_PROMPT`](../../src/language/parser.py#L127) and [`tools`](../../src/language/parser.py#L204)`()` cached, settings and request after | Deliberate ordering, not stylistic. The prompt and the schema are identical on every call, so they are the cache prefix — measured at 2,103 cached tokens against roughly 420 that vary. Putting the current settings in the system prompt would change the prefix on every request and cache nothing |
| 10 | tool_use set_render, scheme navy | [`tools`](../../src/language/parser.py#L204)`()` is generated from [`SPECS`](../../src/control/render_config.py#L74), so a scheme added to `palettes.py` is speakable without editing a schema. `tool_choice` is `any`: one of the two tools and never prose, because a parser that can reply with a paragraph has a third output shape nothing downstream handles. The tools are **not** strict, on purpose — [`RenderConfig`](../../src/control/render_config.py#L118) is already the validator, and an eval that could never observe a malformed delta could not measure how often one is produced |
| 11 | [`Parsed`](../../src/language/parser.py#L274)`(delta, unmet=None, seconds=2.6)` | Exactly one of `delta` and `declined` is set. `unmet` is the third thing and is *not* a refusal: `smallest characters possible` really returned `{"lcd_font_size": 4}` alongside a note that the terminal's character size is not this device's to change. The delta still applies; the sentence explains what it could not cover |
| 12 | [`record`](../../src/language/asklog.py#L90)`(source="model", seconds, usage)` | Written on this thread too, and silently skipped when there is no log. `source` is the load-bearing field — filtering on it is what separates a fact about the prompt from a fact about the table — and `usage` is why the cost of this path can be counted rather than guessed at |
| 13 | [`Ask`](../../src/control/command_server.py#L55)`(utterance, delta, note="2.6s")` | The same shape a table hit produces, so from here nothing can tell which route answered. The note is the difference a person sees: elapsed seconds where a table hit says `instant`, with `unmet` appended after a dash when there is one. The delta itself is still unjudged — [`with_changes`](../../src/control/render_config.py#L141) has not run yet, and will refuse this in the same words it refuses a typed line |

Unlike the shortcut-table scenario, this diagram is banded, because this one
really does cross a thread. The crossing is a single step and it is deliberately
one-way: [`_note`](../../ascii_camera.py#L337) rebinds one tuple that the render
loop reads on its next pass, and hands the same text to `LcdWorker`, whose
[`notice`](../../src/lcd/lcd_worker.py#L143) takes a lock and records rather than
draws. Nothing is drawn from this thread, and nothing waits on the loop — the
picture keeps its frame rate through the whole two and a half seconds.

The one outcome drawn here is the one that succeeds. A parse that raises, and a
request the model declines, are different outcomes with the same cast, and get
their own documents rather than an `alt` in this one.

## Related scenarios

- [A spoken phrase is answered from the shortcut table, with no model call](a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
  — the route taken instead when `look_up` knows the phrase exactly: no key, no
  network, no seconds, and the reason this document begins where it does.
- [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — where the `Ask` produced here goes next. It joins the same inbox a typed
  line does, and by then there is nothing left to wait for.
- [A render configuration change is refused](a-render-configuration-change-is-refused.md)
  — what judges the delta this produces. The model's output earns no special
  treatment, which is the point of letting it through unstrict.
- **A model parse fails and the panel says which kind of failure it was** — the
  `ParseError` outcome, where `short_failure` shortens a sentence to something
  that fits a 320-pixel band.
- **The language model declines a request it cannot satisfy** — the `declined`
  outcome, which is an answer rather than a failure and still has to reach the
  panel rather than only the socket.

*(The unlinked entries above are documents not written yet.)*
