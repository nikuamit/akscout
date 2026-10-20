from jobscout.utils import MAX_DESCRIPTION_LENGTH, strip_html


def test_none_and_empty_input():
    assert strip_html(None) == ""
    assert strip_html("") == ""


def test_plain_tags_are_stripped():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_double_escaped_tags_are_still_stripped():
    # Greenhouse's `content` field comes back HTML-entity-escaped even
    # though it's markup - the tags only become real "<...>" after
    # unescaping once.
    assert strip_html("&lt;h2&gt;&lt;strong&gt;Title&lt;/strong&gt;&lt;/h2&gt;") == "Title"


def test_literal_less_than_in_text_is_not_mistaken_for_a_tag():
    assert strip_html("<p>Score &lt;3 means you need help.</p>") == "Score <3 means you need help."


def test_script_and_style_blocks_removed_with_their_content():
    html_in = (
        "<style>.evil { color: red; }</style>"
        "<p>Real text.</p>"
        "<script>alert(document.cookie)</script>"
    )
    out = strip_html(html_in)
    assert out == "Real text."


def test_html_entities_are_unescaped():
    assert strip_html("Python &amp; PySpark &lt;3") == "Python & PySpark <3"


def test_output_is_capped_at_max_description_length():
    huge = "<p>" + ("word " * 10 * MAX_DESCRIPTION_LENGTH) + "</p>"
    assert len(strip_html(huge)) == MAX_DESCRIPTION_LENGTH
