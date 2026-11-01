from collector.normalize import normalize_title, safe_url, strip_html, trim


def test_strip_html():
    assert strip_html("<p>Hi&nbsp;there</p><script>x()</script><p>Bye</p>") == "Hi there\nBye"
    assert "<" not in strip_html("<img src=x onerror=alert(1)>text")


def test_trim():
    out = trim("word " * 200)
    assert len(out) <= 601 and out.endswith("…")
    assert trim("short") == "short"


def test_safe_url():
    assert safe_url("https://a.b/c") == "https://a.b/c"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("data:text/html,x") is None
    assert safe_url("ftp://a.b") is None


def test_normalize_title():
    assert normalize_title("Hack Night!  @ The LAB") == normalize_title("hack night the lab")
