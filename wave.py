import os
import requests
import json
import time
import base64
import mimetypes
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO
import qrcode
from data_info import *

load_dotenv()
API_KEY = os.getenv("WSAI_KEY")
# Create result folder if it doesn't exist
os.makedirs("result/videos", exist_ok=True)
os.makedirs("result/images", exist_ok=True)

def compress_image(image_path, max_size_kb=900, quality=85):
    """
    Compress image to target size while maintaining quality.
    Only compresses if image is larger than max_size_kb.

    Args:
        image_path: Path to the image file
        max_size_kb: Target maximum size in KB (default 900KB)
        quality: JPEG quality 1-100 (default 85)

    Returns:
        Compressed image as BytesIO object, or None if no compression needed
    """
    try:
        # Check current file size first
        current_size_kb = os.path.getsize(image_path) / 1024

        # If already small enough, return None (no compression needed)
        if current_size_kb <= max_size_kb:
            print(f"Image already optimized: {current_size_kb:.1f}KB (target: {max_size_kb}KB) - skipping compression")
            return None

        print(f"Image size: {current_size_kb:.1f}KB - compressing to {max_size_kb}KB...")

        img = Image.open(image_path)

        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Resize if image is too large (optional - maintains aspect ratio)
        max_dimension = 2048  # Max width or height
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"Resized from {img.size} to {new_size}")

        # Compress to target size
        output = BytesIO()
        current_quality = quality

        while current_quality > 20:  # Don't go below quality 20
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=current_quality, optimize=True)
            size_kb = output.tell() / 1024

            if size_kb <= max_size_kb:
                break

            current_quality -= 5

        output.seek(0)
        print(f"✓ Compressed: {current_size_kb:.1f}KB → {size_kb:.1f}KB (quality: {current_quality})")
        return output

    except Exception as e:
        print(f"Error compressing image: {e}")
        return None


def file_to_base64(file_path, compress=False, max_size_kb=900):
    """
    Helper function to convert a file to a base64 string with the correct MIME type.

    Args:
        file_path: Path to the file
        compress: Whether to compress images (default False)
        max_size_kb: Maximum size in KB for compression (default 900KB)
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        if file_path.endswith(".mp3"):
            mime_type = "audio/mpeg"
        else:
            mime_type = "image/jpeg"

    # Compress image if requested and it's an image file
    if compress and mime_type and mime_type.startswith('image/'):
        compressed = compress_image(file_path, max_size_kb=max_size_kb, quality=85)

        # If compression returned data, use it; otherwise use original
        if compressed:
            encoded_string = base64.b64encode(compressed.read()).decode('utf-8')
            return f"data:{mime_type};base64,{encoded_string}"

    # Standard encoding for non-compressed files or when compression not needed
    with open(file_path, "rb") as f:
        encoded_string = base64.b64encode(f.read()).decode('utf-8')

    return f"data:{mime_type};base64,{encoded_string}"


# CHANGED: Renamed from qwen_edit to nano_banana_edit
def nano_banana_edit(img1, age_gap):
    """
    Edit image using Google Nano Banana Pro API.
    Places user in UAE-themed scene with traditional attire.
    """
    # 1. Convert User Uploaded Image (img1) to Base64 WITH COMPRESSION
    img1_b64 = file_to_base64(img1, compress=True, max_size_kb=900)
    if not img1_b64:
        print("Failed to encode input image")
        return None

    # 2. Define Local Paths
    img2_path = bg_path

    # Costume Image selection
    if age_gap == "Male":
        img3_path = img3_m
        prompt = prompt_m
    elif age_gap == "Female":
        img3_path = img3_f
        prompt = prompt_f
    elif age_gap == "Boy":
        img3_path = img3_b
        prompt = prompt_b
    else:
        img3_path = img3_g
        prompt = prompt_g

    # 3. Convert Local Assets to Base64 WITH COMPRESSION
    img2_b64 = file_to_base64(img2_path, compress=True, max_size_kb=900)
    img3_b64 = file_to_base64(img3_path, compress=True, max_size_kb=900)

    if not img2_b64 or not img3_b64:
        print("Failed to encode background or dress images. Check file paths in 'data' folder.")
        return None

    # CHANGED: API endpoint from Qwen to Nano Banana Pro
    url = "https://api.wavespeed.ai/api/v3/google/nano-banana-pro/edit"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    # CHANGED: Payload structure for Nano Banana Pro
    payload = {
        "aspect_ratio": "9:16",              # NEW: vertical format
        "enable_base64_output": False,
        "enable_sync_mode": False,
        "images": [img1_b64, img2_b64, img3_b64],
        # REMOVED: "loras" field (Qwen-specific)
        "output_format": "jpeg",
        "prompt": prompt,
        "resolution": "1k",                   # CHANGED: from "size": "756*1024"
        # REMOVED: "seed" field
    }

    begin = time.time()
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        result = response.json()["data"]
        request_id = result["id"]
        print(f"✅ Nano Banana task submitted. Request ID: {request_id}")
    else:
        print(f"❌ Error: {response.status_code}, {response.text}")
        return None

    # Poll for results
    url = f"https://api.wavespeed.ai/api/v3/predictions/{request_id}/result"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    max_retries = 360
    retry_count = 0
    while retry_count < max_retries:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            result = response.json()["data"]
            status = result["status"]
            if status == "completed":
                end = time.time()
                print(f"✅ Image edit completed in {end - begin:.1f} seconds.")
                return result["outputs"][0]  # Returns a URL
            elif status == "failed":
                print(f"❌ Task failed: {result.get('error')}")
                return None
            else:
                print(f"⏳ Task processing... Status: {status}")
        else:
            print(f"❌ Error: {response.status_code}, {response.text}")
            return None
        time.sleep(0.1)
        retry_count += 1
    
    print("❌ Task timed out after maximum retries")
    return None


def wans2v(img, age_gap):
    """
    Generate video from edited image using WAN 2.2 speech-to-video.
    """
    # Note: 'img' here is already a URL (output from nano_banana_edit)

    # Select audio and prompt
    if age_gap == "Male":
        audio_path = audio_m
        prompt = prompt_mw
    elif age_gap == "Female":
        audio_path = audio_f
        prompt = prompt_fw
    elif age_gap == "Boy":
        audio_path = audio_b
        prompt = prompt_bw
    else:
        audio_path = audio_g
        prompt = prompt_gw

    # Convert local audio file to Base64
    audio_b64 = file_to_base64(audio_path)
    if not audio_b64:
        print(f"Failed to encode audio file: {audio_path}")
        return None

    url = "https://api.wavespeed.ai/api/v3/wavespeed-ai/wan-2.2/speech-to-video"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "audio": audio_b64,  # Base64 encoded audio
        "image": img,        # URL from previous step
        "prompt": prompt,
        "resolution": "480p",
        "seed": -1
    }

    begin = time.time()
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        result = response.json()["data"]
        request_id = result["id"]
        print(f"✅ Video task submitted. Request ID: {request_id}")
    else:
        print(f"❌ Error: {response.status_code}, {response.text}")
        return None

    # Poll for results
    url = f"https://api.wavespeed.ai/api/v3/predictions/{request_id}/result"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    max_retries = 240
    retry_count = 0
    while retry_count < max_retries:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            result = response.json()["data"]
            status = result["status"]
            if status == "completed":
                end = time.time()
                print(f"✅ Video generation completed in {end - begin:.1f} seconds.")
                return result["outputs"][0]
            elif status == "failed":
                print(f"❌ Task failed: {result.get('error')}")
                return None
            else:
                print(f"⏳ Video processing... Status: {status}")
        else:
            return None
        time.sleep(0.5)
        retry_count += 1
    
    print("❌ Video generation timed out")
    return None


def save_video(url, id):
    """Download and save video from URL."""
    if url is None:
        print("Error: No URL provided")
        return None
    response = requests.get(url)
    if response.status_code == 200:
        file_path = f"result/videos/{id}.mp4"
        with open(file_path, "wb") as f:
            f.write(response.content)
        print(f"✅ Video saved: {file_path}")
        return file_path
    else:
        print(f"❌ Error downloading video: {response.status_code}")
        return None


def save_photo(url, id):
    """Download and save edited image from URL."""
    if url is None:
        print("Error: No URL provided")
        return None
    response = requests.get(url)
    if response.status_code == 200:
        file_path = f"result/images/{id}.jpeg"
        with open(file_path, "wb") as f:
            f.write(response.content)
        print(f"✅ Image saved: {file_path}")
        return file_path
    else:
        print(f"❌ Error downloading image: {response.status_code}")
        return None


def generate_qr_code(video_path):
    """Generate QR code for video download."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )

    # Add the video path to QR code
    qr.add_data(video_path)
    qr.make(fit=True)

    # Create QR code image
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Convert to PIL Image and return
    buffer = BytesIO()
    qr_img.save(buffer, format='PNG')
    buffer.seek(0)

    return Image.open(buffer)
