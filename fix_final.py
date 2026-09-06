import base64
from pathlib import Path

def run():
    input_file = "stady_proxy_404.html"
    output_html = "stady_proxy_404_fixed.html"
    output_img = "404_image.png"

    print(f"🔄 Reading {input_file}...")
    content = Path(input_file).read_text(encoding="utf-8", errors="ignore")

    target = "data:image/png;base64,"
    if target not in content:
        print("❌ Marker not found!")
        return

    before, after = content.split(target, 1)
    
    quote_char = '"'
    if '"' in after:
        base64_raw, rest_of_html = after.split('"', 1)
    elif "'" in after:
        quote_char = "'"
        base64_raw, rest_of_html = after.split("'", 1)
    else:
        print("⚠️ No closing quote found! The file was cut off abruptly.")
        # If truncated, the rest of the file is just the incomplete base64 data
        base64_raw = after
        rest_of_html = "></div></main>"

    # Clean the base64 string
    base64_clean = "".join(base64_raw.split())
    
    # Fix missing padding for truncated base64
    padding_needed = len(base64_clean) % 4
    if padding_needed:
        base64_clean += "=" * (4 - padding_needed)

    # Decode and save image
    try:
        img_bytes = base64.b64decode(base64_clean)
        Path(output_img).write_bytes(img_bytes)
        print(f"✅ Image saved as '{output_img}' ({len(img_bytes)} bytes)")
    except Exception as e:
        print(f"❌ Base64 decode failed: {e}")
        return

    # Build new HTML
    new_html = before + output_img + quote_char + rest_of_html

    # Ensure closing tags exist
    if "</body" not in new_html.lower():
        new_html += "\n</body>"
    if "</html" not in new_html.lower():
        new_html += "\n</html>"

    Path(output_html).write_text(new_html, encoding="utf-8")
    print(f"✅ Created clean HTML: '{output_html}'")
    print("🎉 Success! Try opening 'stady_proxy_404_fixed.html'")

if __name__ == "__main__":
    run()
