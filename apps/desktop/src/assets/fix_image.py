import numpy as np
from PIL import Image

img = Image.open('splash-bg.jpg').convert('RGB')
arr = np.array(img)
H, W, _ = arr.shape
fade_start = int(W * 0.45)
fade_end = int(W * 0.65)
arr[:, :fade_start] = 0
for x in range(fade_start, fade_end):
    fade = (x - fade_start) / (fade_end - fade_start)
    arr[:, x] = (arr[:, x] * fade).astype(np.uint8)

Image.fromarray(arr).save('splash-bg-mesh-only.jpg')
