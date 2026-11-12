"""The one rule for "this is Japanese text", shared by the release preflight
(tools/release/preflight_public.py, private to the monorepo) and the
disc-free sheet lint (tools/translation/lint_sheets.py): a run of at least
JP_RUN Japanese characters (kana, kanji, half-width katakana, then also
Japanese punctuation) is text; shorter runs (a name, a glossary term, a
particle quoted in a note) are not.  No dependencies: the preflight imports
it on its own.
"""
import re

JP_CHAR = '぀-ヿ㐀-䶿一-鿿ｦ-ﾟ'
JP_PUNCT = '　-〿！-･'
JP_RUN = 10                     # characters (preflight --jp-run)
JP_ANY_RE = re.compile('[%s]' % JP_CHAR)


def run_re(min_run=JP_RUN):
    """A run of at least `min_run` Japanese characters."""
    return re.compile('[%s][%s%s]{%d,}' % (JP_CHAR, JP_CHAR, JP_PUNCT, min_run - 1))


def runs(text, min_run=JP_RUN):
    """The runs of `text` that count as Japanese text."""
    return run_re(min_run).findall(text)
