import json
import os

import openai


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline != -1:
        text = text[first_newline + 1 :]
    end = text.rfind("```")
    if end != -1:
        text = text[:end]
    return text.strip()


def main() -> None:
    api_key = os.getenv("POE_API_KEY")
    if not api_key:
        raise SystemExit("POE_API_KEY is not set")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.poe.com/v1",
    )

    system_prompt = (
        "You are a test assistant.\n"
        "Reply ONLY with valid JSON of the form:\n"
        "{\"assistant_message\": \"...\", \"search_keywords\": [\"...\"]}."
    )
    user_prompt = "Find classes related to HTTP client and suggest search keywords."

    chat = client.chat.completions.create(
        model="claude-sonnet-4.5",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = chat.choices[0].message.content
    print("RAW:", content)
    parsed = json.loads(_strip_markdown_fence(content))
    print("assistant_message:", parsed.get("assistant_message"))
    print("search_keywords:", parsed.get("search_keywords"))


if __name__ == "__main__":
    main()
