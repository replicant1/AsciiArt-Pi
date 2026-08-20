"""
One or two ideas per class, for docs/class-overview.md.

The rest of that page is generated: the grouping comes from the package tree,
the headings and the public surface from `ast`. This is the half that cannot
be, because "what is this class *for*" is a judgement about the design and not
a fact recoverable from the source. A first docstring line is a label; this is
meant to be the thing a reader can hold in mind while reading a scenario.

Two rules, and both are enforced by tests/docs/class_map_test.py rather than
trusted: every class in the app has an entry here, and every entry here is for
a class that still exists. A synopsis for something deleted is worse than no
synopsis, because it reads as current.

The rule that is *not* enforced is the one that matters most: a synopsis is
one or two ideas, not an inventory. The method list is directly above it and
already says what the class can do. If a synopsis reads as a comma-separated
tour of its own methods it has failed, however accurate it is.
"""

SYNOPSES = {

    "MainRenderLooper": """
        The whole process hangs off this one object. It owns the render loop,
        and it is the only thread on which a setting may be changed. Every way
        of changing one - a key, the knob, a line off the socket, a phrase a
        language model turned into a delta - ends at its `apply` method. That is
        why there is a single place that knows what each setting costs to
        change.
    """,

    "YuvFrame": """
        One frame from the camera, before anything has been converted. Its
        planes are views into the capture buffer rather than copies, so reading
        the greyscale image costs nothing, and colour costs only the chroma a
        scheme actually asks for. Keeping all three planes together also lets
        the render loop and the panel's thread read the same frame at once,
        since neither of them writes to it.
    """,

    "CameraCapture": """
        Owns the camera and the thread that reads it, and keeps only the newest
        frame in a queue one item deep. When the render loop falls behind it
        therefore loses frames rather than falling behind reality. The camera's
        timing also stays its own, and never comes to depend on how expensive
        the current colour scheme is.
    """,

    "ImageProcessor": """
        Reduces a camera frame to exactly one pixel per character cell.
        Everything downstream works on a few thousand values instead of tens of
        thousands, because this runs first. The luma and chroma planes go
        through the same reduction, which keeps them in register. If they
        drifted apart, colour would fringe along every edge in the picture.
    """,

    "AsciiArt": """
        Turns brightness into characters using a table built once, rather than a
        calculation repeated for every cell. The same table answers two
        questions. The terminal asks for a character, and the panel asks for a
        position in the ramp, because it draws its glyphs from an atlas.
        Deriving both from one table is what stops the two displays disagreeing
        about which character a brightness deserves.
    """,

    "Scheme": """
        One display's whole appearance, held as a value: the lit ink, the unlit
        screen behind it, and which of the three kinds of colour scheme it is.
        It has no behaviour of its own. That is deliberate, because it lets the
        nine schemes be an ordinary list, which the `s` key and the knob step
        through.
    """,

    "HeadlessDisplay": """
        Stands in for the terminal when a run has none, which in the enclosure
        is every run. It draws nothing, but it still holds the settings and
        still reads the keyboard. The app therefore has a single display
        interface, rather than a scattering of checks for whether a screen
        exists.
    """,

    "NcursesDisplay": """
        Draws the picture on the HDMI terminal. While it is running, curses owns
        the screen. That is the fact worth remembering: nothing anywhere else in
        the app may write to standard output or standard error, or the picture
        is corrupted.
    """,

    "ILI9341": """
        The panel itself, at the level of pins and bytes. Everything above it
        works in pixels. Only this class knows the initialisation sequence the
        controller expects, and that a frame has to leave in 4,096-byte pieces,
        because that is all the kernel's SPI buffer will accept.
    """,

    "GlyphAtlas": """
        Holds every character of a ramp, rasterised once into a tile of fixed
        size. Drawing a frame is then a single array lookup. The alternative is
        1,536 separate text-drawing calls per frame, which is the difference
        between the panel keeping up and falling behind.
    """,

    "LcdDisplay": """
        Turns a grid of ramp positions into a frame of RGB565 pixels. Glyph
        coverage is treated as a fade from the scheme's unlit screen colour to
        each cell's own colour, rather than as a stencil. Its frame buffer
        persists between calls, which is what allows a message to be painted
        over a picture that is not being redrawn.
    """,

    "SplashScreen": """
        Gives the panel something to show before there is a picture to show. The
        camera takes about twenty seconds to produce its first frame. In a
        sealed box, twenty seconds of blank glass is indistinguishable from
        broken hardware.
    """,

    "LcdWorker": """
        A thread that owns the panel, so the render loop never waits for the 33
        milliseconds a frame costs over SPI. It is handed the app's whole live
        configuration with each frame, rather than a private copy of the fields
        it cares about. A setting added to the app therefore reaches the panel
        without anyone having to remember to add it in a second place.
    """,

    "Ask": """
        A delta that has already been worked out, on its way to the render loop.
        Its value is that it is a distinct type. An answer that took four
        seconds to obtain from a language model reaches the loop the same way a
        typed line does, and by then nothing about it reveals which it was.
    """,

    "Reply": """
        An answer that never reaches the render loop. It carries a message
        straight back to whoever asked for it. Refusals, help text and
        failures therefore stay off the one thread that has to keep drawing.
    """,

    "CommandServer": """
        The Unix socket, and a thread for each client that connects. It does
        nothing else, on purpose. It accepts a line, offers it to whoever
        resolves it, and leaves the result where the render loop will collect
        it. A request that takes several seconds therefore costs the picture
        nothing.
    """,

    "CommandError": """
        Raised when a typed line cannot be turned into a delta, and it carries
        the reason why. It exists so that the layer settling what type a word
        has can refuse in a sentence rather than in a traceback. Whether a value
        is actually allowed is a separate question, answered elsewhere.
    """,

    "QuadratureDecoder": """
        Takes pin levels and returns detents. It has no GPIO, no thread and no
        clock of its own. That purity is the point rather than tidiness. This is
        the part that can be wrong in a way nobody notices until the knob feels
        bad, so it has to be testable on a machine with no encoder attached.
    """,

    "RotaryEncoder": """
        Claims the knob's three GPIO pins and accumulates what it did, under a
        lock, because the edges arrive on a thread the render loop does not
        control. What it hands over is a net count rather than a list of events.
        The loop therefore learns how far the knob moved, and not how noisily it
        got there.
    """,

    "ConfigError": """
        Raised when a delta is refused, and it carries every reason rather than
        only the first one found. A caller can then correct a whole change in a
        single pass. That also matters to the eval that scores a language
        model's proposals, which wants the entire list.
    """,

    "Spec": """
        Describes what one setting accepts and what it is for. The twelve of
        them are the single source from which the validator, the `help` text,
        the command-line arguments and the language model's tool schema are all
        built. A setting therefore cannot exist in this app and be undocumented,
        and adding one is a single edit.
    """,

    "RenderConfig": """
        Holds the complete live render state. It is frozen, so a change replaces
        it rather than editing it, and no reader can ever catch it half-applied.
        It is also the only code that decides whether a value is allowed. It
        gives the same answer whoever asked, which is what makes comparing a
        keypress, a knob and a language model meaningful.
    """,

    "SchemeCycle": """
        Walks through the colour schemes, whichever input asked for the move. It
        applies a whole banked move at once, rather than one detent at a time.
        Every scheme change repaints every cell, so a spin applied step by step
        would strobe through pictures nobody is on screen long enough to see.
    """,

    "Forwarder": """
        Sends one line to the app's command socket and returns the reply. It is
        the only thing in the web process that knows the camera exists. That
        keeps the phone page a client of the app, rather than a second copy of
        it.
    """,

    "AskLimit": """
        Counts the requests that cost money over a sliding window, and refuses
        them past a ceiling. A phone left face up on a table can post the same
        form for hours. This is the only thing standing between that and an
        unattended API bill.
    """,

    "Handler": """
        Serves one HTTP request: the page itself, the form on it, and the
        forwarding of whatever was typed. Each request runs on a thread of its
        own. One slow ask therefore cannot make the page unreachable for anybody
        else.
    """,

    "WebServer": """
        Listens on the LAN, over IPv4 only, and holds the socket path it
        forwards to. The narrow binding is the security posture. There is no
        authentication anywhere on this path, so what limits the damage is who
        can reach it at all.
    """,

    "AskLog": """
        Writes down every ask, with what it cost and how it was answered. The
        load-bearing part is the source it records. That separates what the
        shortcut table answered for nothing from what a language model was paid
        to answer, which is what makes the hit rate and the cost countable
        rather than estimated.
    """,

    "ParseError": """
        Raised when a parse cannot be completed. A dead network, a refused key
        and a model that declined all arrive as this one type. The caller's job
        is to put something useful on a 240x320 panel, not to tell those three
        apart.
    """,

    "Parsed": """
        What one utterance came back as. Exactly one of the delta and the
        refusal is ever set, so nothing downstream has a third shape to handle.
        The remaining field is the honest one. It says what the request asked
        for that these settings cannot express, which is not the same as being
        refused.
    """,

    "AskResolver": """
        The whole of the ask path, and the one part of the app allowed to be
        slow. It tries the exact table before it even looks for an API key. That
        ordering is why `green` and `freeze it` still work with the network
        down, and why asking is never all or nothing.
    """,

}

# The members each class shows in the diagram at the top of the page.
#
# Not "the public surface" - that is already listed under every heading, and a
# diagram repeating it would be an index rather than a picture. These are the
# members the *synopsis* turns on: read a box and the paragraph below should
# follow from it. `RenderConfig` has twelve fields and shows none of them,
# because what matters about it is that a change produces a new one.
#
# Every name here is checked against the class's real members by
# tests/docs/class_map_test.py, so a rename cannot leave a box describing
# something that no longer exists.
HIGHLIGHTS = {
    "MainRenderLooper": ["config", "apply", "run"],
    "YuvFrame":         ["luma", "chroma"],
    "CameraCapture":    ["frame_queue", "get_frame", "stop"],
    "ImageProcessor":   ["process", "to_grid", "colour_grid"],
    "AsciiArt":         ["index_lut", "to_ascii_text", "to_indices"],
    "Scheme":           ["name", "kind", "ink", "screen"],
    "HeadlessDisplay":  ["scheme", "render", "get_key"],
    "NcursesDisplay":   ["scheme", "render", "get_key"],
    "ILI9341":          ["width", "height", "show_packed", "close"],
    "GlyphAtlas":       ["tiles", "cell_w", "cell_h"],
    "LcdDisplay":       ["render", "show_notice", "grid_size"],
    "SplashScreen":     ["render"],
    "LcdWorker":        ["submit", "notice", "stop"],
    "Ask":              ["utterance", "delta", "note"],
    "Reply":            ["text"],
    "CommandServer":    ["resolver", "take", "stop"],
    "CommandError":     [],
    "QuadratureDecoder": ["feed"],
    "RotaryEncoder":    ["take", "take_presses"],
    "ConfigError":      ["problems"],
    "Spec":             ["name", "kind", "choices", "low", "high"],
    "RenderConfig":     ["with_changes", "changes_from"],
    "SchemeCycle":      ["poll", "step", "home"],
    "Forwarder":        ["send", "alive"],
    "AskLimit":         ["allow"],
    "Handler":          ["do_GET", "do_POST"],
    "WebServer":        ["forwarder", "limit"],
    "AskLog":           ["record"],
    "ParseError":       [],
    "Parsed":           ["delta", "declined", "unmet", "ok"],
    "AskResolver":      ["resolve", "warm"],
}


# The page opens with three class diagrams rather than one.
#
# One diagram of all thirty-one was legible only at arm's length, and most of
# its width came from the nine classes that reference nothing: they have no
# edges to place them, so the layout scatters them. Splitting by what a reader
# is trying to understand puts them in the company that explains them.
#
# The split was chosen by measuring rather than by taste. These three cut
# **no** edges at all - every relationship in the app has both ends inside one
# diagram - and only `MainRenderLooper` appears twice, which is ordinary for a
# hub. tests/docs/class_map_test.py re-derives the edges and fails if any of
# them ever comes to span two diagrams, so a new reference between subsystems
# cannot quietly go missing from the page.
DIAGRAMS = [
    ("The frame's path",
     "Everything one camera frame passes through, from the sensor to the "
     "glass. The densest part of the app, and the only part that runs on "
     "every frame.",
     ["MainRenderLooper", "CameraCapture", "YuvFrame", "ImageProcessor",
      "AsciiArt", "Scheme", "LcdWorker", "SplashScreen", "LcdDisplay",
      "GlyphAtlas", "ILI9341", "NcursesDisplay", "HeadlessDisplay"]),

    ("Getting a change in",
     "Every route by which a setting changes - a typed line, the knob, a "
     "phrase for the model - and the one object that decides whether a value "
     "is allowed. `MainRenderLooper` appears again because it is where all of "
     "them arrive.",
     ["MainRenderLooper", "RenderConfig", "Spec", "ConfigError",
      "CommandServer", "Ask", "Reply", "CommandError", "SchemeCycle",
      "RotaryEncoder", "QuadratureDecoder", "AskResolver", "Parsed",
      "ParseError", "AskLog"]),

    ("The phone page",
     "A second process, sharing no memory with the app and reaching it only "
     "down a Unix socket. Its own diagram because that separation is the most "
     "important thing about it.",
     ["WebServer", "Handler", "AskLimit", "Forwarder"]),
]
