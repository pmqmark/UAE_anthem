import os

# Base directory for the project's data assets (this keeps paths portable)
BASE = os.path.join(os.path.dirname(__file__), "data")

# 1) Define Local Paths for qwen/image assets
bg_path = os.path.join(BASE, "newbg.png")

img3_m = os.path.join(BASE, "male", "dress2.jpeg")
prompt_m = (
    "The man is wearing Emirati thobe. He is in the foreground against a studio "
    "background featuring an illustrated Dubai skyline with the flag , in a clean minimal "
    "line art style with beige and brown tones. half-body image. Professional studio "
    "photography, even lighting, clean composition."
)

img3_f = os.path.join(BASE, "female", "dress.jpeg")
prompt_f = (
    "The woman is wearing a black abaya with UAE flag colors embellished panel and beige hijab. "
    "She is in the foreground against a studio background featuring an illustrated Dubai skyline with the flag. "
    "half-body image,Professional photography, natural daylight, clear sky, realistic composition."
)

img3_b = os.path.join(BASE, "boy", "dress.jpg")
prompt_b = (
    "The boy is wearing Emirati thobe. He is in the foreground against a studio background featuring "
    "an illustrated Dubai skyline with the flag , in a clean minimal line art style with beige and brown tones. "
    "half-body image .Professional studio photography, even lighting, clean composition."
)

# The repository contains `data/girl/dress.jpeg` so use the `.jpeg` extension here
img3_g = os.path.join(BASE, "girl", "dress.jpeg")
prompt_g = (
    "The girl is wearing a UAE flag colors dress. She is in the foreground against a studio background "
    "featuring an illustrated Dubai skyline with the flag. half-body image,  Professional photography, "
    "natural daylight, clear sky, realistic composition"
)


# 2) Define Local Paths for wan (audio + prompts)
audio_m = os.path.join(BASE, "male", "audio1.mp3")
prompt_mw = "The Man is singing UAE national anthem singing"

audio_f = os.path.join(BASE, "female", "audio1.mp3")
prompt_fw = "The woman singing UAE national anthem singing."

audio_b = os.path.join(BASE, "boy", "audio1.mp3")
prompt_bw = "The boy is singing UAE national anthem singing."

audio_g = os.path.join(BASE, "girl", "audio1.mp3")
prompt_gw = "The girl is singing UAE national anthem singing."


def validate_asset_paths(verbose: bool = True) -> bool:
    """Check that required data assets exist on disk. Returns True if all present.

    Use this in development or in CI smoke tests to detect missing files early.
    """
    required = {
        "bg_path": bg_path,
        "img3_m": img3_m,
        "img3_f": img3_f,
        "img3_b": img3_b,
        "img3_g": img3_g,
        "audio_m": audio_m,
        "audio_f": audio_f,
        "audio_b": audio_b,
        "audio_g": audio_g,
    }

    missing = []
    for name, p in required.items():
        if not os.path.exists(p):
            missing.append((name, p))

    if verbose:
        if missing:
            print("Missing data assets:")
            for name, p in missing:
                print(f" - {name}: {p}")
        else:
            print("All configured data files were found.")

    return len(missing) == 0


if __name__ == "__main__":
    validate_asset_paths()
