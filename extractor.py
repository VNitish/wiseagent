BOILERPLATE_HEADERS = {"Was this article helpful?", "Related articles"}

_HEADING_LEVELS = {"h2": "##", "h3": "###", "h4": "####", "h5": "#####"}


def extract_content(tags: list[dict]) -> tuple[str, str]:
    """
    Extract (title, content) from OpenGraph.io tags response.

    Heading levels are preserved in markdown (h2→##, h3→###, h4→####, h5→#####)
    so that chunker.py can reconstruct the section hierarchy.

    Strips:
    - Trailing boilerplate sections ("Was this article helpful?", "Related articles")
    - Last remaining <p> tag (always a CTA / navigation link)
    """
    # Cut off at first boilerplate header (any heading level)
    cutoff = len(tags)
    for i, tag in enumerate(tags):
        if tag["tag"] in _HEADING_LEVELS and tag["innerText"].strip() in BOILERPLATE_HEADERS:
            cutoff = i
            break

    relevant = [t for t in tags[:cutoff] if t["tag"] != "title"]

    # Remove last <p> (CTA / navigation link)
    for i in range(len(relevant) - 1, -1, -1):
        if relevant[i]["tag"] == "p":
            relevant.pop(i)
            break

    # Use <h1> as the article title
    title = next(
        (t["innerText"].strip() for t in relevant if t["tag"] == "h1"),
        "Untitled",
    )

    # Build content — h1 is the title, skip it in body
    parts = []
    for tag in relevant:
        text = tag["innerText"].strip()
        if not text or tag["tag"] == "h1":
            continue
        marker = _HEADING_LEVELS.get(tag["tag"])
        if marker:
            parts.append(f"{marker} {text}")
        else:
            parts.append(text)

    content = "\n\n".join(parts)
    return title, content
