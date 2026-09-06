import base64
from pathlib import Path

def run():
    input_file = "stady_proxy_404.html"
    output_html = "stady_proxy_404_fixed.html"
    output_img = "404_image.png"

    print(f"🔄 Reading {input_file}...")
    if not Path(input_file).exists():
        print(f"❌ {input_file} not found!")
        return

    content = Path(input_file).read_text(encoding="utf-8", errors="ignore")

    target = "data:image/png;base64,"
    if target not in content:
        print("❌ 'data:image/png;base64,' marker not found!")
        return

    print("✅ Found Base64 marker! Splitting string...")
    
    # Split content at the base64 start
    before, after = content.split(target, 1)
    
    # Find the closing quote (either " or ')
    quote_char = '"' if '"' in after else "'"
    base64_raw, rest_of_html = after.split(quote_char, 1)

    # Clean base64 string
    base64_clean = "".join(base64_raw.split())

    # Decode and save image
    try:
        img_bytes = base64.b64decode(base64_clean)
        Path(output_img).write_bytes(img_bytes)
        print(f"✅ Image extracted successfully to '{output_img}' ({len(img_bytes)} bytes)")
    except Exception as e:
        print(f"❌ Base64 decode failed: {e}")
        return

    # Create new clean HTML
    new_html = before + output_img + quote_char + rest_of_html

    # Ensure closing tags exist
    if "</body" not in new_html.lower():
        new_html += "\n</body>"
        print("🔧 Appended </body> tag.")
    if "</html" not in new_html.lower():
        new_html += "\n</html>"
        print("🔧 Appended </html> tag.")

    Path(output_html).write_text(new_html, encoding="utf-8")
    print(f"✅ Created clean HTML: '{output_html}'")
    print("🎉 Success! Base64 is removed without changing design.")

if __name__ == "__main__":
    run()
