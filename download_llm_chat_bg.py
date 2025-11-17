import argparse
import os
import sys
import urllib.request


def download_image(url: str, out_path: str) -> None:
    # Always use the local proxy on port 2805, as requested
    proxy_url = "http://127.0.0.1:2805"
    proxy_handler = urllib.request.ProxyHandler({
        "http": proxy_url,
        "https": proxy_url,
    })
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)

    print(f"[llm-chat-bg] Downloading image from: {url}")
    print(f"[llm-chat-bg] Using proxy: {proxy_url}")

    with urllib.request.urlopen(url) as resp:
        data = resp.read()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(f"[llm-chat-bg] Saved background to: {out_path}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Download a hacker-style background image for the LLM chat window."
    )
    parser.add_argument(
        "--url",
        default=(
            "https://images.unsplash.com/photo-1518770660439-4636190af475"
            "?auto=format&fit=crop&w=1600&q=80"
        ),
        help="Image URL to download. Default is a generic code/hacker wallpaper from Unsplash.",
    )
    parser.add_argument(
        "--target-dir",
        default=".",
        help="Directory where llm_chat_bg.png will be written (default: current directory).",
    )

    args = parser.parse_args(argv)

    target_dir = os.path.abspath(args.target_dir)
    out_path = os.path.join(target_dir, "llm_chat_bg.png")

    try:
        download_image(args.url, out_path)
    except Exception as ex:  # noqa: BLE001
        print(f"[llm-chat-bg] ERROR: {ex}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

