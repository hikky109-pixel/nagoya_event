from PIL import Image
import pytesseract

img = Image.open("images/test.png")

text = pytesseract.image_to_string(
    img,
    lang="jpn"
)

print(text)