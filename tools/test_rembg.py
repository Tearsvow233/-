from rembg import remove
from rembg.session_factory import new_session
from PIL import Image

src = r"D:\agent\BabyCat\assets\_preview\prev_009.jpg"
dst = r"D:\agent\BabyCat\assets\_preview\prev_009_rgba.png"

print("Creating u2netp session...")
session = new_session("u2netp")
print("Session OK:", session.model_name)

im = Image.open(src)
out = remove(im, session=session)
out.save(dst)
print(f"saved {dst} size={out.size}")
