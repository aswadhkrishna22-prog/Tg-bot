import re
import base64
from pathlib import Path

def fix_html_file():
    input_file = "stady_proxy_404.html"
    output_html = "stady_proxy_404_fixed.html"
    output_img = "404_image.png"

    print(f"🔄 Checking {input_file}...")
    
    try:
        # Read the HTML file
        html_content = Path(input_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"❌ File {input_file} not found!")
        return

    # Updated Regex to handle newlines between <img and src=
    pattern = r'(<img[^>]*?src\s*=\s*["\'])(data:image/[a-zA-Z]+;base64,)([^"\']+)(["\'])'
    
    # re.DOTALL (re.S) is crucial here to match across newlines
    match = re.search(pattern, html_content, re.DOTALL | re.IGNORECASE)

    if match:
        prefix = match.group(1)      # <img... src="
        base64_data = match.group(3) # The actual base64 string
        suffix = match.group(4)      # Closing quote "

        print("✅ Base64 image data found. Extracting...")

        # Remove newlines and spaces from Base64 string
        clean_base64 = base64_data.replace('\n', '').replace('\r', '').replace(' ', '')

        # 1. Decode and save the image
        try:
            image_bytes = base64.b64decode(clean_base64, validate=False)
            Path(output_img).write_bytes(image_bytes)
            print(f"✅ Image successfully saved as '{output_img}'.")
        except Exception as e:
            print(f"❌ Error saving image: {e}")
            return

        # 2. Replace Base64 in HTML with the new image filename
        start, end = match.span()
        new_html = html_content[:start] + f'{prefix}{output_img}{suffix}' + html_content[end:]

        # 3. Fix missing closing tags if necessary
        if "<body" in new_html.lower() and "</body>" not in new_html.lower():
            new_html += "\n</body>"
            print("🔧 Added missing </body> tag.")
        if "<html" in new_html.lower() and "</html>" not in new_html.lower():
            new_html += "\n</html>"
            print("🔧 Added missing </html> tag.")

        # 4. Save the new HTML file
        try:
            Path(output_html).write_text(new_html, encoding="utf-8")
            print(f"✅ New HTML file saved as '{output_html}'.")
            print("\n🎉 All done! You can now use 'stady_proxy_404_fixed.html'.")
        except Exception as e:
            print(f"❌ Error saving new HTML: {e}")

    else:
        print("❌ No Base64 image data found in this file.")

if __name__ == "__main__":
    fix_html_file()
