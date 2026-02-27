BOILERPLATE_HEADERS = {"Was this article helpful?", "Related articles"}


def extract_content(tags: list[dict]) -> tuple[str, str]:
    """
    Extract (title, content) from OpenGraph.io tags response.

    Strips:
    - Browser <title> tag (contains " | Wise Help Centre" suffix)
    - Trailing boilerplate sections ("Was this article helpful?", "Related articles")
    - Last remaining <p> tag (always a CTA / navigation link)
    """
    # Cut off at first boilerplate header
    cutoff = len(tags)
    for i, tag in enumerate(tags):
        if tag["tag"] in ("h3", "h4") and tag["innerText"].strip() in BOILERPLATE_HEADERS:
            cutoff = i
            break

    relevant = [t for t in tags[:cutoff] if t["tag"] != "title"]

    # Remove last <p> (e.g. "Learn how to get a transfer receipt")
    for i in range(len(relevant) - 1, -1, -1):
        if relevant[i]["tag"] == "p":
            relevant.pop(i)
            break

    # Use <h1> as the article title
    title = next(
        (t["innerText"].strip() for t in relevant if t["tag"] == "h1"),
        "Untitled",
    )

    # Build content — h1 becomes the implicit title so skip it here
    parts = []
    for tag in relevant:
        text = tag["innerText"].strip()
        if not text or tag["tag"] == "h1":
            continue
        if tag["tag"] in ("h2", "h3", "h4"):
            parts.append(f"## {text}")
        else:
            parts.append(text)

    content = "\n\n".join(parts)
    return title, content
