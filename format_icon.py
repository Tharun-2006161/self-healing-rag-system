from PIL import Image, ImageOps

input_path = r"C:\Users\win\.gemini\antigravity\brain\aec8920a-0d18-4c7d-b97a-468cd7247f12\media__1779533124335.png"
output_path = r"C:\Users\win\RAG_SYSTEM\au_chatbot_icon.png"

# Open the image
img = Image.open(input_path)

# Android icons must be exactly 512x512
size = (512, 512)

# Pad it with black background so it doesn't stretch or warp the logo
padded_img = ImageOps.pad(img, size, color=(0, 0, 0))

# Save it as a PNG format (which is required by app makers)
padded_img.save(output_path, "PNG")
print(f"Successfully saved perfect 512x512 icon to {output_path}")
