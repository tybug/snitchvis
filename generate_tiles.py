import os

import requests
from PIL import Image

ROOT_URL = "https://raw.githubusercontent.com/civmc-map/tiles/master/terrain/z0/"

print("downloading tiles from map.civmc.tk...")

for i in range(-40, 40 + 1):
    for j in range(-40, 40 + 1):
        print(f"downloading {i},{j}.png")
        r = requests.get(f"{ROOT_URL}{i}%2C{j}.png")
        if r.status_code == 404:
            img = Image.new("RGB", (256, 256), (0, 0, 0))
            img.save(f"{i},{j}.png")
        else:
            with open(f"{i},{j}.png", "wb") as f:
                f.write(r.content)

print("tiles downloaded")
print("combining tiles vertically")

for i in range(-40, 40 + 1):
    ims = [f"{i},{j}.png" for j in range(-40, 40 + 1)]
    os.system(f"convert {' '.join(ims)} -append {i}.png")

print("combining vertically-combined tiles horizontally")
ims = [f"{i}.png" for i in range(-40, 40 + 1)]
os.system(f"convert {' '.join(ims)} +append combined.png")

print("combined into full image")
_ = input("crop combined.png to 20001x20001 and move to final.png. Press "
    "enter when finished")

print("cropping to 400x400 tiles")
os.system('magick final.png -crop 400x400 -set filename:tile '
    '"%[fx:page.x/400-25]_%[fx:page.y/400-25]" +repage +adjoin '
    '"%[filename:tile].png"')
