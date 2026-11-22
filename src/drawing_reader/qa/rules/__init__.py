"""The rule answerers, grouped by what they answer from.

Each rule has the signature `rule(question_lowercase, tokens, index) -> Answer | None` and returns
None when the question is not its kind. The order rules are tried in lives in `qa.router.RULES`.
"""
