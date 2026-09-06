import re
import base64
from pathlib import Path

def fix_html_file():
    input_file = "stady_proxy_404.html"
    output_html = "stady_proxy_404_fixed.html"
    output_img = "404_image.png"

    print(f"🔄 ഫയൽ {input_file} പരിശോധിക്കുന്നു...")
    
    try:
        # HTML ഫയൽ റീഡ് ചെയ്യുന്നു
        html_content = Path(input_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"❌ {input_file} എന്ന ഫയൽ കണ്ടെത്താനായില്ല!")
        return

    # Updated Regex to handle newlines between <img and src=
    pattern = r'(<img[^>]*?src\s*=\s*["\'])(data:image/[a-zA-Z]+;base64,)([^"\']+)(["\'])'
    # re.DOTALL (re.S) is crucial here to match across newlines
    match = re.search(pattern, html_content, re.DOTALL | re.IGNORECASE)

    if match:
        prefix = match.group(1)      # <img... src="
        base64_data = match.group(3) # The actual base64 string
        suffix = match.group(4)      # Closing quote "

        print("✅ Base64 ഇമേജ് ഡാറ്റ കണ്ടെത്തി. എക്സ്ട്രാക്റ്റ് ചെയ്യുന്നു...")

        # Base64 കോഡിൽ നിന്നും വരികളും സ്പേസും ഒഴിവാക്കുന്നു
        clean_base64 = base64_data.replace('\n', '').replace('\r', '').replace(' ', '')

        # 1. ഇമേജ് ഡീകോഡ് ചെയ്ത് സേവ് ചെയ്യുന്നു
        try:
            image_bytes = base64.b64decode(clean_base64, validate=False)
            Path(output_img).write_bytes(image_bytes)
            print(f"✅ ഇമേജ് വിജയകരമായി '{output_img}' എന്ന പേരിൽ സേവ് ചെയ്തു.")
        except Exception as e:
            print(f"❌ ഇമേജ് സേവ് ചെയ്യുന്നതിൽ പിഴവ് സംഭവിച്ചു: {e}")
            return

        # 2. HTML-ൽ Base64 മാറ്റി ഇമേജ് ഫയലിന്റെ പേര് കൊടുക്കുന്നു
        start, end = match.span()
        new_html = html_content[:start] + f'{prefix}{output_img}{suffix}' + html_content[end:]

        # 3. മിസ്സിംഗ് ആയ ടാഗുകൾ ഫിക്സ് ചെയ്യുന്നു
        if "<body" in new_html.lower() and "</body>" not in new_html.lower():
            new_html += "\n</body>"
            print("🔧 </body> ടാഗ് ചേർത്തു.")
        if "<html" in new_html.lower() and "</html>" not in new_html.lower():
            new_html += "\n</html>"
            print("🔧 </html> ടാഗ് ചേർത്തു.")

        # 4. പുതിയ HTML ഫയൽ സേവ് ചെയ്യുന്നു
        try:
            Path(output_html).write_text(new_html, encoding="utf-8")
            print(f"✅ പുതിയ HTML ഫയൽ '{output_html}' എന്ന പേരിൽ സേവ് ചെയ്തു.")
            print("\n🎉 എല്ലാം കഴിഞ്ഞു! ഇനി 'stady_proxy_404_fixed.html' ഉപയോഗിക്കാം.")
        except Exception as e:
            print(f"❌ പുതിയ HTML സേവ് ചെയ്യുന്നതിൽ പിഴവ്: {e}")

    else:
        print("❌ ഈ ഫയലിൽ Base64 ഇമേജ് ഡാറ്റ കണ്ടെത്താനായില്ല. (റെജെക്സ് വീണ്ടും പരാജയപ്പെട്ടു)")

if __name__ == "__main__":
    fix_html_file()
