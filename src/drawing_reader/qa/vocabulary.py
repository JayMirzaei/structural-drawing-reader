"""Word lists the rules share: what counts as a member word, a generic topic word, a property word."""

from __future__ import annotations

# leftover words a "list the sheets" question can carry without actually asking for a topic filter
SHEET_LISTING_WORDS = {"title", "titles", "name", "names", "number", "numbers", "scale", "scales"}


# leftover words a "what is <sheet> about" question can carry without naming an actual topic to filter on
SHEET_ABOUT_WORDS = {
    "title",
    "titles",
    "name",
    "names",
    "about",
    "describe",
    "description",
    "content",
    "contents",
    "contain",
    "contains",
    "cover",
    "covers",
    "summary",
    "summarize",
}


# generic sheet/view *type* words -- common across many unrelated sheets ("FRONT ELEVATION DETAILS",
# "CONNECTION DETAILS" both contain "details"), so on their own they're too weak to filter a sheet
# listing by; rule_sheets' topic match only trusts one of these alone when no more specific word is
# also present in the same question (see its use below).
GENERIC_SHEET_TOPIC_WORDS = {
    "detail",
    "details",
    "plan",
    "plans",
    "elevation",
    "elevations",
    "schedule",
    "schedules",
    "note",
    "notes",
    "drawing",
    "drawings",
    "section",
    "sections",
    "view",
    "views",
}


# generic callout-question words that never appear as part of a detail's actual title, so they
# don't count as part of a free-text detail description when rule_callouts tries to match a view title
GENERIC_CALLOUT_WORDS = {"callout", "callouts", "reference", "references", "referencing", "refer", "refers"}


LOAD_TOPIC_WORDS = {
    "snow",
    "wind",
    "seismic",
    "earthquake",
    "soil",
    "load",
    "loads",
    "pressure",
    "force",
    "forces",
    "period",
    "vibration",
    "acceleration",
    "concrete",
    "strength",
    # "live"/"dead": without these, both reduce to the generic "load" topic word, so "what is the
    # live load?" would match a "DEAD LOAD" fact just because both mention "load" (a set can state
    # a dead load and no live load at all).
    "live",
    "dead",
}


# General-notes material clauses commonly file plate/gusset steel under a "CONNECTIONS" component
# rather than a "PLATES" component of its own -- these synonyms are tried only when a question
# token has zero exact component matches (see rule_materials).
MATERIAL_COMPONENT_SYNONYMS = {"plate": ("connection",), "gusset": ("connection", "plate"), "connection": ("plate",)}


MEMBER_WORDS = {
    "column": ("vertical", ("W", "HSS", "C", "L")),
    "columns": ("vertical", ("W", "HSS", "C", "L")),
    "post": ("vertical", ("W", "HSS")),
    "brace": ("diagonal", ("HSS", "W", "L", "C")),
    "braces": ("diagonal", ("HSS", "W", "L", "C")),
    "diagonal": ("diagonal", ("HSS", "W", "L", "C")),
    "beam": ("horizontal", ("W", "HSS", "C", "S")),
    "beams": ("horizontal", ("W", "HSS", "C", "S")),
    "strut": ("horizontal", ("HSS", "W")),
    "struts": ("horizontal", ("HSS", "W")),
    "girder": ("horizontal", ("W",)),
    "tie": ("horizontal", ("HSS", "W")),
    # A stair stringer runs diagonally (a typical note: "STAIR STRINGERS: C250X30"); joist/purlin/girt/kicker/chord are common structural-steel
    # member words this vocabulary was otherwise missing entirely. "header" deliberately excluded --
    # too easily confused with a document/schedule header, not just a structural member.
    "stringer": ("diagonal", ("C", "W", "HSS", "L")),
    "stringers": ("diagonal", ("C", "W", "HSS", "L")),
    "joist": ("horizontal", ("W", "HSS", "C")),
    "joists": ("horizontal", ("W", "HSS", "C")),
    "purlin": ("horizontal", ("C", "W", "HSS")),
    "purlins": ("horizontal", ("C", "W", "HSS")),
    "girt": ("horizontal", ("C", "W")),
    "girts": ("horizontal", ("C", "W")),
    "kicker": ("diagonal", ("HSS", "W", "L", "C")),
    "kickers": ("diagonal", ("HSS", "W", "L", "C")),
    "chord": ("horizontal", ("W", "HSS", "L", "C", "S")),
    "chords": ("horizontal", ("W", "HSS", "L", "C", "S")),
}


# Words that make a materials question generic (nothing component-specific to match).
GENERIC_MATERIAL_WORDS = {
    "material",
    "materials",
    "steel",
    "grade",
    "grades",
    "specified",
    "specify",
    "specification",
    "general",
    "notes",
    "note",
    "used",
    "strength",
    "yield",
    "tensile",
    "stress",
    "minimum",
    "maximum",
    "required",
    "standard",
    "standards",
    "which",
    "what",
    "this",
    "these",
    "project",
    "building",
    "structure",
}


# post-tokens()/SYN word sets for each property a "one component, several properties" lookup can
# name (rule_multi_property below) -- used both to detect that shape of question and, via
# COMPONENT_PROPERTY_TOKENS, to keep "grade"/"size" words out of rule_component_spec's own
# component-name matching (they're properties answered by other rules, not part of the name).
PROPERTY_CLASSES = {
    "thick": {"thick", "thk"},
    "long": {"long", "length"},
    "dia": {"dia", "diam"},
    "grade": {"grade", "fy", "astm", "csa", "material", "materials", "yield"},
    "size": {"size"},
}


COMPONENT_PROPERTY_TOKENS = (
    {"thick", "thk", "long", "length", "dia", "diam"} | PROPERTY_CLASSES["grade"] | PROPERTY_CLASSES["size"]
)


# Member/direction words repeat across many unrelated view titles on a structural set ("FRONT
# ELEVATION - COLUMN", "TOP COLUMN", "MIDDLE COLUMN", "BOTTOM COLUMN" all contain "column") -- same
# generic-word-alone problem as GENERIC_SHEET_TOPIC_WORDS, so rule_views' own title match prefers a
# more specific word (e.g. "splice") over these when the question has one.
GENERIC_VIEW_TOPIC_WORDS = (
    GENERIC_SHEET_TOPIC_WORDS
    | set(MEMBER_WORDS)
    | {"front", "side", "top", "bottom", "middle", "connection", "connections"}
)


DIMENSION_TRIGGER_WORDS = {
    "height",
    "heights",
    "tall",
    "high",
    "rise",
    "vertical",
    "width",
    "widths",
    "wide",
    "spacing",
    "bay",
    "bays",
    "span",
    "horizontal",
    "dimension",
    "dimensions",
    "length",
    "lengths",
    "long",
    "size",
    "sizes",
}


# Content words that still describe a plain dimension question (so an unanchored list is acceptable).
GENERIC_DIM_WORDS = {
    "overall",
    "total",
    "largest",
    "biggest",
    "longest",
    "typical",
    "building",
    "structure",
    "frame",
    "main",
    "distance",
    "between",
    "center",
    "centre",
    "centres",
    "centers",
    "grid",
    "grids",
    "line",
    "lines",
    "tier",
    "tiers",
    "width",
    "widths",
    "column",
    "columns",
    "spacing",
    "spacings",
    "bay",
    "bays",
    "span",
    "spans",
    "height",
    "heights",
    "wide",
    "long",
    "vertical",
    "horizontal",
    "dimension",
    "dimensions",
    "strings",
}
