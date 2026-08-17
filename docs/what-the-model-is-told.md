# What the model is told

Everything the natural-language layer knows about this camera, in one place:
the system prompt and the tool schema, exactly as `src/parser.py` sends them.

Section 5 is the deliberate complement — the 41 eval cases, which are the one
thing kept *out* of what the model sees, and which are what say whether any of
the rest is working.

**This is a snapshot and it will go stale.** Both halves are read out of the
code at call time, so the running system cannot drift from the code — but this
file can drift from both. Regenerate it rather than trusting it:

    cd AsciiArt-Pi
    python3 -c "import sys; sys.path.insert(0,'src'); import parser; print(parser.SYSTEM_PROMPT)"
    python3 -c "import sys, json; sys.path.insert(0,'src'); import parser; print(json.dumps(parser.tools(), indent=2))"

Neither needs a key or the network — `parser.py` imports the SDK lazily, inside
`_client()`, so both commands run on the Mac with nothing installed.

Section 5 is a hand-written reading of `tests/eval_cases.json`; that file is the
authority, and this listing was checked to quote all 41 of its utterances
verbatim rather than transcribed by eye.

Captured at commit `c1b57ff`, 17 August 2026; section 5 added at `5a1c9f4`.
Line numbers cited below are as of that commit and are the first thing to
rot — `grep -n` for the symbol if one looks wrong.

---

## Nothing here is trained

Worth stating plainly, because everything below is easier to misread otherwise.

**"The model" means `claude-opus-5`, running on Anthropic's servers, rented by
the call.** It is stock and unmodified — the same general-purpose Claude anyone
else calling that API gets. It is not on the Pi. There is no model file in this
repo. `parse()` reaches it over HTTPS at `parser.py:333`, which is the only
billable line in the project and the reason nothing works without a network.

**Nothing in this project trains anything.** No dataset, no training run, no
fine-tuning. The proof is one line: `MODEL = "claude-opus-5"` at `parser.py:49`
is an off-the-shelf model string. Fine-tuning would have meant a training job, a
custom model ID, and a separate bill; none of those exist here.

So what makes a general-purpose model understand this camera? Only the
684-token glossary in the system prompt. Claude already knows English, and
already knows amber is warmer than cyan. The one thing it cannot know is that
*this device's* warm schemes are called `amber` and `lime` — so it is told, in a
paragraph, on every single call.

### The translator

> You hire a competent translator. You do not train them — they already speak
> the language. You hand them **a one-page glossary of your company's jargon**
> (the system prompt) and **a form to fill in** (the tool schema). Then,
> separately, you write **41 test sentences with model answers** and mark how
> they did (the eval cases). The translator never sees your answer key. If they
> did, the test would prove nothing.

Everything in this file falls out of that:

| In the analogy | Here | Section |
| --- | --- | --- |
| The translator | `claude-opus-5`, over the network | — |
| The glossary | `SYSTEM_PROMPT` | 1 |
| The form | the tool schema, from `SPECS` | 2 |
| The clerk who rejects a badly filled form | `RenderConfig.with_changes()` | 4 |
| The marked test, kept in a drawer | `tests/eval_cases.json` | 5 |
| Rewriting a confusing glossary entry | a text edit, then re-run the eval | 6 |

`eval_cases.json` is a **test suite**, in exactly the sense `render_config_test.py`
is. That file does not train `RenderConfig`; it checks it. Same relationship.
The only reason the eval cases *feel* like training data is that they are the
same shape as training data — inputs paired with correct outputs. Same shape,
opposite purpose. Using them to write the prompt would be testing on your own
training set: a wonderful score that means nothing.

Three consequences worth holding on to:

- **Changing behaviour is a text edit, not a training run.** Paragraph 6 of the
  prompt took one sentence and a re-run.
- **The model can be swapped by changing one string.** The eval is what tells
  you what a cheaper one costs you in accuracy.
- **The eval scores the glossary, not the model.** Almost every failure it has
  produced was a fixable prompt or schema problem — or a bug in the case file.

---

## 1. The system prompt

684 tokens, 2,139 characters. Wrapped here for reading; as sent it is 19 lines,
because the `\` continuations in the source join each paragraph into one long
line. The blank lines between paragraphs are real.

```
You turn spoken or typed requests into settings changes for an ASCII art camera -
a Raspberry Pi that renders its camera feed as characters, on two displays at
once: a terminal window on an HDMI monitor, and a 2.4 inch LCD panel of 320x240
pixels.

Call set_render with only the settings that should change. Leave everything else
out; omitted settings keep their current values. Call decline when the request
does not describe a change to these settings.

What the vocabulary means on this device:

- Warmer means the amber or lime schemes; cooler means cyan, navy or azure.
  Green is the classic phosphor terminal look, paper is e-ink on white.
- Blockier, chunkier or simpler characters means the coarse ramp; finer, more
  detailed or more shades means the fine ramp.
- Bigger or chunkier *on the panel* means a larger lcd_font_size, which gives
  fewer, larger characters. This is separate from the character ramp.
- The little screen, the panel and the LCD all mean target lcd. The big screen,
  the monitor and the terminal mean target terminal.
- Posterised, banded, or fewer colours means lowering colour_levels. This only
  affects the live-colour scheme.
- Punchier or more contrast means raising contrast; flatter means lowering it.
- Freeze, hold and pause mean freeze on. The picture stops but settings keep
  working, so a frozen picture can still be adjusted.

Requests are often relative - warmer, a bit less, back to normal. You are told
the current settings and the ones before the last change, so resolve them
against those and emit absolute values. Undo means returning the settings that
last changed to what they were before.

A request can ask for several things at once, and can ask for something you can
only partly do. Do the part that maps to a setting rather than declining the
whole thing, and say what you could not do in the `unmet` field.

Change only what the request mentions. Do not change a second setting in order
to make the first one take effect: the person may have chosen the current
settings deliberately, and a change they did not ask for is worse than one that
is not yet visible. Say so in `unmet` instead.
```

### Why each paragraph is there

| ¶ | Does what | Would break without it |
| --- | --- | --- |
| 1 | Says what the device is, including the panel's real size | "bigger characters on the little screen" reads as the character ramp |
| 2 | Sparse deltas; `decline` is a legitimate answer | Every utterance gets an answer, including "asdfgh" |
| 3 | The glossary — this device's vocabulary | "warmer" has no defined meaning here |
| 4 | Relative requests resolve against `now`/`before` | `undo` is impossible; "a bit more" has no anchor |
| 5 | Partial answers, via `unmet` | "make it green and turn the volume up" gets refused whole |
| 6 | Scope discipline | A one-setting request quietly changes two |

Paragraph 3 is the only genuinely hand-authored knowledge in the system. Nothing
else could supply it — that amber is warmer than cyan is general knowledge, but
that *this camera's* warm schemes are amber and lime is not.

Paragraph 6 is the newest, added 17 August 2026 after the eval caught the model
clamping `colour_levels` to its ceiling (right) and *also* switching `scheme` to
`live` so the change would be visible (overreach — the person may be in grey
deliberately). `tests/eval_cases.json` → `invalid-colour-levels` is the guard on
it, and the case note says so.

---

## 2. The tool schema

1,300 tokens. Generated by `parser.tools()` from `render_config.SPECS` — never
written by hand. Short `enum` arrays put on one line here to fit; values are
exactly as generated.

```json
[
  {
    "name": "set_render",
    "description": "Change one or more of the camera's render settings. Include only the settings that should change.",
    "input_schema": {
      "type": "object",
      "properties": {
        "scheme": {
          "type": "string",
          "enum": ["grey", "live", "green", "amber", "cyan",
                   "navy", "azure", "lime", "paper"],
          "description": "Colour scheme the picture is drawn in."
        },
        "ramp": {
          "type": "string",
          "enum": ["coarse", "fine"],
          "description": "Character set, ordered light to dark."
        },
        "invert": {
          "type": "boolean",
          "description": "Reverse the ramp, for a light background."
        },
        "colour_levels": {
          "type": "integer",
          "minimum": 2,
          "maximum": 32,
          "description": "Steps per channel in the live-colour scheme, on both displays; fewer means heavier banding. The maximum means as many as the display can manage - full colour on the panel, the whole xterm cube in the terminal, which saturates at 6 whatever this says. From 2 to 32."
        },
        "contrast": {
          "type": "number",
          "minimum": 0.1,
          "maximum": 4.0,
          "description": "Contrast multiplier about mid-grey; 1.0 leaves the frame alone. From 0.1 to 4.0."
        },
        "auto_levels": {
          "type": "boolean",
          "description": "Stretch each frame's own brightness range to fill 0-255."
        },
        "rotation": {
          "type": "integer",
          "enum": [0, 90, 180, 270],
          "description": "Camera rotation in degrees, applied before any mirroring."
        },
        "mirror": {
          "type": "boolean",
          "description": "Flip the picture left to right, after any rotation."
        },
        "fill": {
          "type": "boolean",
          "description": "Crop the picture to fill the whole window instead of letterboxing it. The panel always fills and ignores this."
        },
        "lcd_font_size": {
          "type": "integer",
          "minimum": 4,
          "maximum": 16,
          "description": "Glyph size on the SPI panel, which sets its character grid. 6, 8 and 9 tile the panel exactly; other sizes leave a black margin. From 4 to 16."
        },
        "target": {
          "type": "string",
          "enum": ["both", "terminal", "lcd"],
          "description": "Which display shows the picture."
        },
        "freeze": {
          "type": "boolean",
          "description": "Hold the last frame instead of taking new ones. Settings still apply, so a frozen picture can be adjusted and watched."
        },
        "unmet": {
          "type": "string",
          "description": "Anything the request asked for that these settings cannot express. Omit when the request was fully satisfied."
        }
      },
      "additionalProperties": false
    }
  },
  {
    "name": "decline",
    "description": "The request does not describe a change to the camera's settings - it is unintelligible, or asks for something this device does not do.",
    "input_schema": {
      "type": "object",
      "properties": {
        "reason": {
          "type": "string",
          "description": "One short sentence a person would find useful, addressed to them."
        }
      },
      "required": ["reason"],
      "additionalProperties": false
    }
  }
]
```

### What to notice

**Every `description` is a `note` from SPECS.** The same string produces the
CLI's `help` text. Written once, so a fact learned the hard way — that the
terminal saturates at 6 colour levels whatever you ask for — reaches both the
model and the person typing, and cannot be updated in one place and not the
other.

**`"additionalProperties": false`,** so the model cannot invent a field. With
the enums, this is why `RenderConfig` has never rejected a real model reply
across every eval run so far.

**No `required` on `set_render`, but `required: ["reason"]` on `decline`.** A
delta is sparse by nature. A refusal with no reason is useless to whoever is
standing at the camera.

**`unmet` is the thirteenth property and is not a setting.** It is the escape
hatch behind paragraph 5. `parse()` pops it back out before the delta goes near
`RenderConfig`, which would otherwise reject it as unknown.

**Booleans are tested before integers** in `_json_type()`. In Python `bool`
subclasses `int`, so `isinstance(True, int)` is true and `rotation` and
`invert` would both render as integers. The same trap made
`False in (0, 90, 180, 270)` evaluate true in the validator.

**Deliberately not `strict`.** Strict tool use would demand all thirteen fields
on every call, and "unchanged" would have to be spelled as an explicit null
twelve times. More to the point, an eval that could never *observe* a malformed
delta could not measure how often one happens.

---

## 3. What it costs

Measured with `messages.count_tokens`, which is not billed.

| | tokens | note |
| --- | ---: | --- |
| System prompt | 684 | identical every call |
| Tool schema | 1,300 | identical every call |
| **Cached prefix** | **1,984** | what `cache_control` protects |
| Settings + utterance | ~150 | varies, full price |
| Reply | ~150 | short think plus one tool call |

The schema is nearly twice the prompt, and is the larger half of what caching
saves. At list prices the prefix is $0.0099 uncached against $0.00099 cached —
about **0.7p per ask**, roughly a third of a full eval run's bill.

This is why the current settings go in the **user** turn and not the system
prompt. The prompt and schema are byte-identical every call and so are the cache
prefix; settings change every call, and putting them up top would move the
prefix and cache nothing. `parser.py:337` says so in a comment, because it is
the kind of thing that gets tidied by someone who does not know it is
load-bearing.

---

## 4. Where it all comes from

```
                    render_config.SPECS
                    (one declaration)
                       │            │
        commands.py ◀──┘            └──▶ parser.py
        text grammar                     JSON tool schema
             │                                 │
   you type "scheme amber"        you say "make it warmer"
             │                                 │
             └────────▶ RenderConfig.with_changes() ◀───────┘
                        (the only validator)
                                 │
                              hardware
```

Two front ends, one declaration, one validator. The model is a *parser*, not an
executor: it proposes a delta and stops. Nothing it emits reaches the hardware
without `with_changes()` first, and from the app's side a parsed delta and a
typed one are indistinguishable.

Consequences worth keeping in mind:

- **Adding a setting to `RenderConfig` teaches both front ends at once.** It
  appears in `help` and in the tool schema the moment it exists.
  `_check_specs_match_fields()` raises at import if SPECS and the dataclass
  drift, so this cannot be half-done.
- **Changing behaviour is a text edit, not a training run.** Paragraph 6 above
  took one sentence, a file copy to the Pi, and a re-run. There is no dataset
  and no fine-tuning anywhere in this project.
- **`tests/eval_cases.json` is held out.** Its 41 cases only ever *grade* the
  prompt, never write it. A prompt derived from its own test cases would score
  well and tell you nothing.

## 5. What it is never told — the eval cases

Everything above is input to the model. This section is the opposite: the 41
cases in `tests/eval_cases.json` are **held out**. They only ever *grade* the
prompt, and are never used to write it. A prompt derived from its own test cases
would score beautifully and tell you nothing.

Read the file itself for the authoritative version — its `_about` header
documents the case format (`expect`, `now`, `before`, `allow`, `forbid`,
`or_decline`, `or_delta`, `unmet`). What follows is the set as of `5a1c9f4`,
with the reasoning behind each group, which the JSON has no room for.

`now:` is the config the utterance resolves against, where it matters.

### Plain — one setting, no ambiguity (5)

| utterance | expected |
| --- | --- |
| make it green | `scheme: green` |
| rotate the picture 90 degrees | `rotation: 90` |
| invert it | `invert: true` |
| freeze the picture | `freeze: true` |
| flip it left to right | `mirror: true` |

The floor. If these fail nothing else matters.

### Vocabulary — the device's own words (6)

| utterance | expected |
| --- | --- |
| make it warmer | `scheme: amber` or `lime` |
| something cooler | `scheme: cyan`, `navy` or `azure` |
| blockier characters please *(now: fine)* | `ramp: coarse` |
| give me finer detail | `ramp: fine` |
| that's too punchy, flatten it out *(now: 2.5)* | `contrast: 0.1–2.0` |
| bigger characters on the little screen | `lcd_font_size: 9–16`, **forbid** `ramp` |

The last is the trap: panel glyph size and the character ramp are different
things, and confusing them is the likeliest wrong answer on this device. It is
the only case in the set with a `forbid`.

### Relative — meaningless without state (5)

| utterance | state | expected |
| --- | --- | --- |
| a bit more contrast | now 1.0 | `1.05–2.0` |
| way more contrast | now 1.0 | `2.0–4.0` |
| undo that | now 2.5, before 1.0 | `contrast: 1.0` |
| undo that | now amber + fine, before grey + coarse | `scheme: grey, ramp: coarse` |
| put everything back to normal | now lime, 3.0, inverted | `grey, 1.0, invert false` |

The two contrast cases are a matched pair and must come out *different*, or the
model is ignoring the modifier and the bands are hiding it. The two `undo` cases
differ in how many fields the last change touched.

### Several at once (4)

"amber, and freeze it there" · "green, high contrast, and the fine character
set" · "back to plain greyscale and unfreeze" · "unfreeze it, and while you're
there make it cyan".

The last has its second instruction in a parenthetical, which is where a parser
that latches onto the first verb comes unstuck.

### Named looks — judgement, not lookup (4)

"make it look like the Matrix" → green · "make it look like an old cash
machine" → amber or green · "make it look like a Kindle" → paper or azure ·
"something calmer" → any of five.

These carry `allow` lists: a ramp or contrast choice alongside the scheme is
taste, not error. Scoring them strictly would be scoring an opinion.

### Displays (4)

"put it on the little screen only" · "same but on the big screen" · "show it on
both again" · "just the monitor please".

Between them these exercise every synonym paragraph 3 of the prompt defines.

### Partial — do half, admit the rest (3)

"make it green and turn the volume up" · "warmer, and email the picture to my
sister" · "zoom in a bit and make it amber".

All three set `unmet: true`, so staying silent about the impossible half scores
as a miss even when the possible half is perfect. Declining the whole request is
also wrong. The zoom case allows `fill`, which crops and is close but not the
same thing.

### Should be declined (5)

"asdfgh" · "what's the weather like" · "make me a sandwich" · "how many colour
schemes are there" · "hmm".

The fourth is the interesting one: a question, not an instruction. Answering it
by changing the scheme would be wrong. Without this group a parser that always
guesses would outscore an honest one.

### Out of range on purpose (5)

| utterance | expected |
| --- | --- |
| rotate it 45 degrees | decline, **or** a legal rotation |
| turn the contrast up to eleven | `contrast: 4.0` (clamp), or decline |
| switch to the sepia scheme | decline, or nearest warm — never `"sepia"` |
| give me a thousand colour levels | `colour_levels: 32`, or decline |
| set the contrast to minus five | decline, or `0.1–1.0` |

These test the boundary rather than the model: `RenderConfig` must be the thing
that says no, not the schema. `or_decline` and `or_delta` exist for exactly this
group — where a sensible clamp and an honest refusal are both good answers, and
insisting on one would be scoring taste.

The colour-levels case doubles as the guard on the prompt's scope rule; see
section 1.

### What the harness does with them

`tests/parser_eval.py` scores **field by field**, not pass/fail per utterance —
two of three right on a three-part request is worth knowing, and a boolean would
throw it away. Three shapes of expectation, because three kinds of question:

    "green"                exactly this
    ["amber", "lime"]      any of these — warm is not one colour
    {"min": .., "max": ..} anywhere in this band — relative asks have no
                           single right answer

Outcomes land in seven buckets, and `refused-correctly` is one of them.

Each case carries its own starting config, so they run in any order and four at
a time, and a wrong answer at case 3 cannot corrupt case 30.

It is deliberately **not** in the suite the other tests run in. It costs about
13p and needs the network, so it is a test you choose to run:

    python3 tests/parser_eval.py                 # the whole set
    python3 tests/parser_eval.py --only decline  # cases whose id contains this
    python3 tests/parser_eval.py --jobs 1        # serially, for clean logs
    python3 tests/parser_eval.py --save runs/    # keep the raw results

It exits 0 at or above a 90% pass rate, 1 below — not 100%, because a threshold
a stochastic component can only meet on a good day is a threshold that gets
ignored.

### What it has actually caught

Not hypothetical. In its first day:

- The `colour_levels` overreach that produced paragraph 6 of the prompt.
- A **concurrency bug in `parser.py`** — a client built per call, so two threads
  racing into their first `anthropic.Anthropic()` hit pydantic's non-thread-safe
  lazy model building. It surfaced as one flaky case in forty and read like a
  flaky model until someone read the message. The CLI is serial and would never
  have shown it.
- Its own noise floor, ±2–3%, which is the only reason we knew to believe three
  runs rather than one.
- Two bugs in the case file itself, where a case failed on a missing `allow`
  rather than on the model's answer. Worth saying plainly: changing a test after
  watching it fail is exactly how an eval gets quietly gamed, so both edits are
  recorded in the case notes.

## 6. Changing it safely

1. Edit the prompt in `src/parser.py`, or a `note` in `src/render_config.py`.
2. `bash sync.sh push` — or copy the file into the mount.
3. `python3 tests/parser_eval.py --jobs 4 --save runs/` on the Pi. Costs ~13p.
4. **Run it more than once.** Run-to-run variance on this set is about ±2–3%;
   roughly one case in 41 flips between identical runs. A single green run
   cannot distinguish a real improvement from noise — the scope fix above was
   confirmed with five runs of the single case plus three full runs, against
   98/100/98 before it.
