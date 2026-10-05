def format_entry_text(text: str, limit: int = 700) -> str:
    """Keep paragraph breaks without generating Markdown quote markers."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text or "（空）"
