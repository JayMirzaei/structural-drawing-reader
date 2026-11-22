"""Provinces, territories and states: the region names an address line can end in.

A data table, so no region is special: every Canadian province and territory and every US state (and
the District of Columbia) with its postal abbreviation. The location reader builds its patterns from
this table; add a row to teach it another region.
"""

from __future__ import annotations

import re

# (postal abbreviation, name as printed on drawings, in capitals)
REGIONS: tuple[tuple[str, str], ...] = (
    # Canada
    ("AB", "ALBERTA"),
    ("BC", "BRITISH COLUMBIA"),
    ("MB", "MANITOBA"),
    ("NB", "NEW BRUNSWICK"),
    ("NL", "NEWFOUNDLAND AND LABRADOR"),
    ("NS", "NOVA SCOTIA"),
    ("NT", "NORTHWEST TERRITORIES"),
    ("NU", "NUNAVUT"),
    ("ON", "ONTARIO"),
    ("PE", "PRINCE EDWARD ISLAND"),
    ("QC", "QUEBEC"),
    ("SK", "SASKATCHEWAN"),
    ("YT", "YUKON"),
    # United States
    ("AL", "ALABAMA"),
    ("AK", "ALASKA"),
    ("AZ", "ARIZONA"),
    ("AR", "ARKANSAS"),
    ("CA", "CALIFORNIA"),
    ("CO", "COLORADO"),
    ("CT", "CONNECTICUT"),
    ("DE", "DELAWARE"),
    ("DC", "DISTRICT OF COLUMBIA"),
    ("FL", "FLORIDA"),
    ("GA", "GEORGIA"),
    ("HI", "HAWAII"),
    ("ID", "IDAHO"),
    ("IL", "ILLINOIS"),
    ("IN", "INDIANA"),
    ("IA", "IOWA"),
    ("KS", "KANSAS"),
    ("KY", "KENTUCKY"),
    ("LA", "LOUISIANA"),
    ("ME", "MAINE"),
    ("MD", "MARYLAND"),
    ("MA", "MASSACHUSETTS"),
    ("MI", "MICHIGAN"),
    ("MN", "MINNESOTA"),
    ("MS", "MISSISSIPPI"),
    ("MO", "MISSOURI"),
    ("MT", "MONTANA"),
    ("NE", "NEBRASKA"),
    ("NV", "NEVADA"),
    ("NH", "NEW HAMPSHIRE"),
    ("NJ", "NEW JERSEY"),
    ("NM", "NEW MEXICO"),
    ("NY", "NEW YORK"),
    ("NC", "NORTH CAROLINA"),
    ("ND", "NORTH DAKOTA"),
    ("OH", "OHIO"),
    ("OK", "OKLAHOMA"),
    ("OR", "OREGON"),
    ("PA", "PENNSYLVANIA"),
    ("RI", "RHODE ISLAND"),
    ("SC", "SOUTH CAROLINA"),
    ("SD", "SOUTH DAKOTA"),
    ("TN", "TENNESSEE"),
    ("TX", "TEXAS"),
    ("UT", "UTAH"),
    ("VT", "VERMONT"),
    ("VA", "VIRGINIA"),
    ("WA", "WASHINGTON"),
    ("WV", "WEST VIRGINIA"),
    ("WI", "WISCONSIN"),
    ("WY", "WYOMING"),
)

# Other spellings of a name in the table.
NAME_ALIASES: tuple[str, ...] = ("NEWFOUNDLAND", "QUÉBEC", "YUKON TERRITORY")

REGION_CODES: tuple[str, ...] = tuple(code for code, _ in REGIONS)

# Longest first, so that in a pattern "WEST VIRGINIA" is tried before "VIRGINIA".
REGION_NAMES: tuple[str, ...] = tuple(sorted((*(name for _, name in REGIONS), *NAME_ALIASES), key=len, reverse=True))

# Names of one word, for comparing against a single word a scan may have misread.
SINGLE_WORD_REGION_NAMES: tuple[str, ...] = tuple(name for name in REGION_NAMES if " " not in name)

COUNTRY_NAMES: tuple[str, ...] = ("CANADA", "USA", "U.S.A.", "UNITED STATES")

NAMES_PATTERN = "|".join(re.escape(name) for name in REGION_NAMES)
CODES_PATTERN = "|".join(REGION_CODES)

# A Canadian postal code ("Z9Z 9Z9" shape: letter, digit, letter, digit, letter, digit) or a US ZIP code ("00000",
# "00000-0000").
POSTAL_PATTERN = r"(?:[A-Z]\d[A-Z]\s?\d[A-Z]\d|\d{5}(?:-\d{4})?)(?![A-Za-z0-9])"
