"""Generate QR Poster directly for testing"""
import sys
sys.path.insert(0, 'c:/Workspace/OryxLab_Pro')

import qrcode
from PIL import Image, ImageDraw, ImageFont
import io
import os

# Generate QR
door_token = "ORYX_LAB_DOOR_2025"
checkin_url = f"http://192.168.0.1:5000/checkin?door_token={door_token}"

qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_L,
    box_size=20,
    border=2,
)
qr.add_data(checkin_url)
qr.make(fit=True)
qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')

# Create A4 Canvas
width, height = 1240, 1754  # A4 portrait ratio
canvas = Image.new('RGB', (width, height), 'white')
draw = ImageDraw.Draw(canvas)

# Load Fonts
font_path = "C:/Windows/Fonts/malgun.ttf"
bold_path = "C:/Windows/Fonts/malgunbd.ttf"

try:
    header_font = ImageFont.truetype(bold_path, 70)
    title_font = ImageFont.truetype(bold_path, 110)
    desc_font = ImageFont.truetype(font_path, 45)
    footer_font = ImageFont.truetype(font_path, 30)
except:
    header_font = ImageFont.load_default()
    title_font = ImageFont.load_default()
    desc_font = ImageFont.load_default()
    footer_font = ImageFont.load_default()

# Draw
header_height = 180
draw.rectangle([0, 0, width, header_height], fill="#003366")
draw.text((width/2, header_height/2), "지혜마루 작은 도서관", font=header_font, fill="white", anchor="mm")

draw.text((width/2, header_height + 140), "입실 체크인", font=title_font, fill="black", anchor="mm")

qr_size = 650
qr_img = qr_img.resize((qr_size, qr_size))
qr_x = (width - qr_size) // 2
qr_y = header_height + 280
canvas.paste(qr_img, (qr_x, qr_y))

text_y = qr_y + qr_size + 50
draw.text((width/2, text_y), "스마트폰 카메라를 켜고", font=desc_font, fill="#555", anchor="mm")
draw.text((width/2, text_y + 60), "위 QR 코드를 스캔하세요", font=desc_font, fill="#555", anchor="mm")

draw.text((width/2, height - 80), "문의: 관리자 호출", font=footer_font, fill="#999", anchor="mm")

# Save
output_path = "c:/Users/hongs/.gemini/antigravity/brain/670da5e4-2e96-4f71-b5ba-260edf85ea43/qr_poster_test.png"
canvas.save(output_path, format='PNG')
print(f"Saved to {output_path}")
