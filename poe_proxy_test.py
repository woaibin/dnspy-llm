import os

import openai


def main() -> None:
    proxy = os.getenv("DNSPY_LLM_HTTP_PROXY")
    print("DNSPY_LLM_HTTP_PROXY:", proxy)

    client = openai.OpenAI(
        api_key=os.getenv("POE_API_KEY") or "uQA9T24fMZ10fF05WJi79MqlShUGH9ZMM7Ip1dzXgho",
        base_url="https://api.poe.com/v1",
    )

    chat = client.chat.completions.create(
        model="claude-sonnet-4.5",
        messages=[{"role": "user", "content": "Hello through proxy"}],
    )
    print("RESPONSE:", chat.choices[0].message.content)


if __name__ == "__main__":
    main()

