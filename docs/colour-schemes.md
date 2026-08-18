## Colour schemes

`s` steps through nine looks, each imitating a real screen. There are no names
on screen — press `s` until you like what you see and stop. The active one
reads out in the status bar as `sch:amber`.

| # | Name | Ink | Screen | Imitates |
|---|------|-----|--------|----------|
| 1 | `grey` | `#FFFFFF` | `#000000` | Plain greyscale: characters only, no colour |
| 2 | `live` | from the camera | `#000000` | Live colour from the scene |
| 3 | `green` | `#33FF33` | `#001A00` | Green phosphor terminal |
| 4 | `amber` | `#FFB733` | `#1A0D00` | Amber CRT |
| 5 | `cyan` | `#66E6FF` | `#001419` | Ice-blue vacuum fluorescent |
| 6 | `navy` | `#EAF6FF` | `#0B3FBF` | White on a blue-backlit character LCD |
| 7 | `azure` | `#123A9E` | `#DFE6E2` | Blue STN LCD on grey-white |
| 8 | `lime` | `#14210A` | `#C4DC1E` | Black on an acid-lime backlight |
| 9 | `paper` | `#2B2B28` | `#E9E7DF` | E-ink on paper |

`grey` and `live` are the two original modes, kept unchanged and placed next to
each other at the head of the cycle. Schemes 3 to 6 have dark screens, 7 to 9
light ones, so cycling walks a deliberate arc rather than jumping about.

![The nine colour schemes, all rendering one frame](scheme-montage.png)

*All nine schemes, and the comparison is a fair one: every tile is the same
picture. One frame was captured, the character grid computed from it once, and
each tile then reuses that identical grid of ramp positions — only the colour
lookup differs. Nothing else can vary, because nothing else is recomputed.*

Regenerate it with `python3 tools/scheme_montage.py`, which renders through the
panel's own glyph atlas and blend, so the tiles show what the app really draws
rather than an impression of it. It asserts its own claim before writing the
file: each tile is reduced to which pixels a glyph covers, and those masks must
agree. Eight of the nine are checked that way. `live` is checked structurally
instead, because its ink comes from the scene — a cell the camera saw as nearly
black renders nearly black whether a glyph covers it or not, so "is a glyph
here" genuinely cannot be recovered from its pixels.

### Why these nine

They come from photographs of real displays, but not one scheme per photograph:
twelve reference images collapsed to fewer distinct *looks* than files. Three
were amber or yellow CRTs, two were green screens, two were black on a lime
backlight. A plain yellow-on-black was dropped outright for sitting only 25
degrees of hue from `amber` — near enough that nobody cycling past would be
sure which one they were looking at.

Being unmistakable matters more here than being numerous, and it is checked
rather than asserted. `tests/art/palette_test.py` compares every pair of schemes by
redmean perceptual distance and **fails the run** if any two are closer than
150. The closest surviving pair is `azure`/`paper` at 223. That is what stops
someone later adding a second amber that differs in the third hex digit.

### How a scheme is drawn

`grey` and `live` work as they always did. The other seven are *tinted*: each
cell blends from the scheme's screen colour to its ink, by how dense a character
the ramp chose for that cell. A bright part of the scene gets both a denser
glyph and fuller-strength ink, which is how a brighter patch of a real CRT
actually behaves.

The blend has to track how much ink the glyph lays down, **not** how bright the
scene was. Those are the same thing until `i` is pressed. `AsciiArt` reverses
its character string on invert but still indexes it from brightness, so a bright
cell keeps a high index while picking a *sparse* glyph. Tinting by that raw
index left bright cells at full-strength ink while drawing them nearly empty —
the characters went negative and the colour did not. The blend table is
reversed to match, so both halves of the picture invert together. This was
caught by the test, not by reading the code.

### Light-screen schemes and the terminal background

`azure`, `lime` and `paper` need one thing the others do not.

The LCD panel is straightforward: the app writes every one of its 76,800
pixels, so "the screen is lime" just means writing lime into the ones no glyph
covers. A terminal does not work that way. You place characters, and each
character carries only its *ink* colour — whatever lies behind the glyph stays
whatever the window already was, which is black.

Setting only the ink for `paper` would therefore give dark grey characters on
black, and the picture would all but vanish. So each scheme's screen colour is
attached to every colour pair as its **background**, and to the window itself,
which covers the padding around the picture and any cell not written that frame.

### Cost

Tinted schemes are cheaper than `live`, because neighbouring cells of equal
brightness get the *same* colour, so runs stay long and ncurses emits fewer
escape sequences. Only `live` needs the coarser grid; the tinted schemes keep
the full one. All nine hold 15.0 fps on the HDMI terminal at 120x43.

On the ILI9341 panel, measured on the Zero 2:

| LCD path | Frame time |
|----------|------------|
| `grey` | 35.7 ms (28 fps) |
| `live` | 46.8 ms (21 fps) |
| tinted, light screen | 54.0 ms (18 fps) |

Schemes with a black screen take a `uint16` fast path in the packer. Making
that code general enough for arbitrary screen colours had cost `live` about
7 ms a frame, so the special case earns its keep.

If a terminal cannot manage 256 colours, `s` skips every scheme but `grey` and
logs the fact.
