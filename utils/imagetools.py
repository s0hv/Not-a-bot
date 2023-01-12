"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
import os
import subprocess
from io import BytesIO
from threading import Lock

import aiohttp
import geopatterns
import magic
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageSequence
from colorthief import ColorThief as CF
from colour import Color
from geopatterns.utils import promap
from numpy import sqrt

from bot.exceptions import (ImageSizeException, ImageResizeException,
                            TooManyFrames, ImageDownloadError,
                            ImageProcessingError)
from bot.globals import IMAGES_PATH

# import cv2
cv2 = None  # Remove cv2 import cuz it takes forever to import

logger = logging.getLogger('terminal')

MAGICK = os.environ.get('MAGICK_PREFIX', '')

MAX_COLOR_DIFF = 2.82842712475  # Biggest value produced by color_distance
GLOW_LOCK = Lock()
TRIMMING_LOCK = Lock()


def make_shiftable(color):
    # Color stays almost the same when it's too close to white or black
    max_dist = MAX_COLOR_DIFF * 0.05
    if color_distance(color, Color('white')) < max_dist:
        color.set_hex('#EEEEEE')
    elif color_distance(color, Color('black')) < max_dist:
        color.set_hex('#333333')

    return color


class ColorThief(CF):
    def __init__(self, img):  # skipcq: PYL-W0231
        if isinstance(img, Image.Image):
            self.image = img
        else:
            self.image = Image.open(img)


class GeoPattern(geopatterns.GeoPattern):
    available_generators = [
        'bricks',
        'hexagons',
        'overlapping_circles',
        'overlapping_rings',
        'plaid',
        'plus_signs',
        'rings',
        'sinewaves',
        'squares',
        'triangles',
        'xes'
    ]

    def __init__(self, string, generator=None, color=None, scale=None,
                 opacity=1.0):
        if isinstance(color, Color):
            color = color.get_hex_l()

        super().__init__(string, generator=generator, color=color, scale=scale,
                         opacity=opacity)

    def generate_background(self, base_color, randomize_hue):
        hue_offset = promap(int(self.hash[14:][:3], 16), 0, 4095, 0, 359)
        sat_offset = int(self.hash[17:][:1], 16)

        if randomize_hue:
            base_color.hue = base_color.hue - hue_offset

        if sat_offset % 2:
            base_color.saturation = min(base_color.saturation + sat_offset / 100, 1.0)
        else:
            base_color.saturation = abs(base_color.saturation - sat_offset / 100)

        rgb = base_color.rgb
        r = int(round(rgb[0] * 255))
        g = int(round(rgb[1] * 255))
        b = int(round(rgb[2] * 255))
        return self.svg.rect(0, 0, '100%', '100%', **{
            'fill': 'rgba({}, {}, {}, {})'.format(r, g, b, self.opacity)
        })


# https://stackoverflow.com/a/3753428/6046713
def replace_color(im, color1, color2):
    """

    Args:
        im: Image
        color1: tuple of 3 integers. Color to be replaced
        color2: tuple of 3 integers. Color that replaces the other color

    Returns:
        new image object
    """

    im = im.convert('RGBA')

    data = np.array(im)  # "data" is a height x width x 4 numpy array
    red, green, blue, _ = data.T  # Temporarily unpack the bands for readability skipcq: PYL-E0633

    r, g, b = color1
    # Replace white with red... (leaves alpha values alone...)
    white_areas = (red == r) & (blue == b) & (green == g)
    data[..., :-1][white_areas.T] = color2  # Transpose back needed
    im = Image.fromarray(data)

    return im


def sepia(im, strength=0.75):
    image = BytesIO()
    im.save(image, 'PNG')
    args = '{}convert - -sepia-tone {:.0%} -evaluate Uniform-noise 7 png:-'.format(MAGICK, strength)
    p = subprocess.Popen(args.split(' '), stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    p.stdin.write(image.getvalue())
    out, err = p.communicate()
    buff = BytesIO(out)
    del image
    return Image.open(buff)


# http://effbot.org/zone/pil-sepia.htm
def sepia_filter(im):
    def make_linear_ramp(white):
        # putpalette expects [r,g,b,r,g,b,...]
        ramp = []
        r, g, b = white
        for i in range(255):
            if i == 0:
                i = 100
            elif i == 254:
                i = 200
            ramp.extend((int(r * i / 255), int(g * i / 255), int(b * i / 255)))
        return ramp

    # make sepia ramp (tweak color as necessary)
    sepia = make_linear_ramp((250, 225, 175))

    # convert to grayscale
    if im.mode != "L":
        im = im.convert("L")

    # optional: apply contrast enhancement here, e.g.
    #im = ImageOps.autocontrast(im)

    # apply sepia palette
    im.putpalette(sepia)

    return im


def trim_image(im):
    ulc = im.getpixel((0, 0))
    if not (ulc == im.getpixel((0, im.height-1)) or ulc == im.getpixel((im.width-1, im.height-1))
            or ulc == im.getpixel((im.width-1, 0))):
        return im

    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)


# http://stackoverflow.com/a/9085524/6046713
def color_distance(c1, c2):
    rmean = (c1.red + c2.red) / 2
    r = c1.red - c2.red
    g = c1.green - c2.green
    b = c1.blue - c2.blue
    return sqrt((int((512+rmean)*r*r) >> 8) + 4*g*g + (int((767-rmean)*b*b) >> 8))


# http://stackoverflow.com/a/38478744/6046713
def complementary_color(my_hex):
    """Returns complementary RGB color"""
    if my_hex[0] == '#':
        my_hex = my_hex[1:]
    rgb = (my_hex[0:2], my_hex[2:4], my_hex[4:6])
    comp = ['%02X' % (255 - int(a, 16)) for a in rgb]
    return '#' + ''.join(comp)


# http://stackoverflow.com/a/24164270/6046713
def bg_from_texture(img, size, mode='RGB'):
    # The width and height of the background tile
    bg_w, bg_h = img.size

    # Creates a new empty image, RGB mode, and size of size
    new_im = Image.new(mode, size)

    # The width and height of the new image
    w, h = new_im.size

    # Iterate through a grid, to place the background tile
    for i in range(0, w, bg_w):
        for j in range(0, h, bg_h):
            # paste the image at location i, j:
            new_im.paste(img, (i, j))

    return new_im


def get_color(img, quality=5):
    cf = ColorThief(img)
    return cf.get_color(quality)


def get_palette(img, colors=6, quality=5):
    cf = ColorThief(img)
    return cf.get_palette(colors, quality=quality)


def create_geopattern_background(size, s, color=None, generator='overlapping_circles'):
    pattern = GeoPattern(s, generator=generator, color=color)
    args = '{}convert -size 100x100 svg:- png:-'.format(MAGICK)
    p = subprocess.Popen(args.split(' '), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p.stdin.write(pattern.svg_string.encode('utf-8'))
    out, err = p.communicate()
    buff = BytesIO(out)
    img = Image.open(buff)
    img = bg_from_texture(img, size)
    return img, pattern.base_color


async def image_from_url(url, get_raw=False):
    if get_raw:
        return await raw_image_from_url(url)

    return Image.open(await raw_image_from_url(url))


async def raw_image_from_url(url, get_mime=False):
    if not url:
        raise ImageDownloadError('No images found', '')

    url = url.strip('\u200b \n')
    data = None
    mime_type = None
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(url) as r:
                logger.debug('Downloading image url {}'.format(url))
                if not r.headers.get('Content-Type', '').startswith('image'):
                    raise ImageDownloadError("url isn't an image (Invalid header)", url)

                max_size = 8_000_000
                size = int(r.headers.get('Content-Length', 0))
                if size > max_size:
                    raise ImageDownloadError('image too big', url)

                data = BytesIO()
                chunk = 4096
                total = 0
                async for d in r.content.iter_chunked(chunk):
                    if total == 0:
                        mime_type = magic.from_buffer(d, mime=True)
                        total += chunk
                        if not mime_type.startswith('image') and mime_type != 'application/octet-stream':
                            raise ImageDownloadError("url isn't an image", url)

                    total += chunk
                    if total > max_size:
                        raise ImageDownloadError('image is too big', url)

                    data.write(d)
        data.seek(0)
    except aiohttp.ClientError:
        logger.exception(f'Could not download image {url}')
        raise ImageDownloadError('unknown error', url)

    if data is None:
        raise ImageDownloadError('unknown error', url)

    if get_mime:
        return data, mime_type
    return data


def shift_color(color, amount):
    if amount == 0:
        return color

    def shift_value(val):
        if val <= 0.5:
            return val * 0.035 * (1 + (amount/20))
        else:
            return val * 0.035 * (1 - (amount/20))

    color = make_shiftable(color)

    sat = color.saturation
    hue = color.hue
    if round(hue, 3) == 0:
        hue = 200

    if round(sat, 3) == 0:
        sat = 0.1

    color.saturation = min(abs(sat * (1 + amount/20)), 1.0)
    color.hue = shift_value(hue)

    return color


def create_glow(img, amount):
    image_path = os.path.join(IMAGES_PATH, 'text.png')
    glow_path = os.path.join(IMAGES_PATH, 'glow.png')

    with GLOW_LOCK:
        try:
            img.save(image_path, 'PNG')
            args = '{}convert {} -blur 0x{} {}'.format(MAGICK, image_path, amount, glow_path)
            subprocess.call(args.split(' '))
            args = '{}composite -compose multiply {} {} png:-'.format(MAGICK, glow_path, image_path)
            p = subprocess.Popen(args.split(' '), stdout=subprocess.PIPE)
            out = p.stdout.read()
            buff = BytesIO(out)
        except Exception:
            logger.exception('Could not create glow')
            return img

    return Image.open(buff)


def create_shadow(img, percent, opacity, x, y):
    import shlex
    args = '{}convert - ( +clone -background black -shadow {}x{}+{}+{} ) +swap ' \
           '-background transparent -layers merge +repage png:-'.format(MAGICK, percent, opacity, x, y)
    p = subprocess.Popen(shlex.split(args), stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    stdin = p.stdin
    image = BytesIO()
    img.save(image, format='PNG')
    stdin.write(image.getvalue())
    del image
    out, err = p.communicate()
    buffer = BytesIO(out)
    img = Image.open(buffer)
    return img


def crop_to_square(img, crop_to_center=True):
    if img.width == img.height:
        return img

    side = min(img.size)
    size = (side, side)
    if crop_to_center:
        w, h = img.size
        x = 0
        y = 0
        if side == w:
            y = (h-side)//2
        else:
            x = (w-side)//2
        img = img.crop((x, y, *size))
    else:
        img = img.crop((0, 0, *size))

    return img


def resize_keep_aspect_ratio(img, new_size, crop_to_size=False, can_be_bigger=True,
                             center_cropped=False, background_color=None,
                             resample=Image.NEAREST, max_pixels=8294400):
    """
    Args:
        img: Image to be cropped
        new_size: Size of the new image
        crop_to_size: after resizing crop image so it's exactly the specified size
        can_be_bigger:
            Tells if the image can be bigger than the requested size
            When true image will be as big or bigger in one dimension than requested size
        center_cropped: Center the image. Used in combination with crop_to_size
                        since otherwise the added or removed space will only be in the
                        bottom right corner
        background_color: Color of the background
        resample: The type of resampling to use
        max_pixels: Maximum amount of pixels the image can have

    Returns:
        Image.Image
    """
    x, y = img.size
    if 0 < max_pixels < x * y:  # More pixels than in a 4k pic is a max by default
        raise ImageSizeException(x * y, max_pixels)

    new_x = new_size[0]
    new_y = new_size[1]

    if new_x is not None and new_y is not None:
        x_m = x / new_x
        y_m = y / new_y
        check = y_m <= x_m if can_be_bigger else y_m >= x_m
    elif new_x is None:
        check = True
    elif new_y is None:
        check = False

    if check:
        m = new_size[1] / y
    else:
        m = new_size[0] / x

    new_x, new_y = int(x * m), int(y * m)
    if max_pixels > 0 and new_x * new_y > max_pixels//2:
        raise ImageResizeException(new_x * new_y, max_pixels//2)

    img = img.resize((new_x, new_y), resample=resample)
    if crop_to_size:
        if center_cropped:
            w, h = img.size
            x_ = 0
            y_ = 0
            if w != x:
                x_ = -int((new_size[0] - w)/2)
            if h != y:
                y_ = -int((new_size[1] - h)/2)
            img = img.crop((x_, y_, new_size[0] + x_, new_size[1] + y_))
        else:
            img = img.crop((0, 0, *new_size))

    if background_color is not None:
        im = Image.new(img.mode, img.size, background_color)
        im.paste(img, mask=img)
        img = im
    return img


def create_text(s, font, fill, canvas_size, point=(10, 10)):
    text = Image.new('RGBA', canvas_size)
    draw = ImageDraw.Draw(text)
    draw.text(point, s, fill, font=font)
    return text


def get_duration(frames):
    if isinstance(frames[0].info.get('duration', None), list):
        duration = frames[0].info['duration']
    else:
        duration = [frame.info.get('duration', 20) for frame in frames]
    return duration


def fixed_gif_frames(img, func=None):
    if func is None:
        def func(im):  # skipcq: PYL-E0102
            return im.copy()

    frames = []
    while True:
        try:
            frames.append(func(img))
        except ValueError as e:
            e = str(e)
            if e.startswith('tile cannot'):
                raise ImageProcessingError(str(e))
            else:
                raise ImageProcessingError()
        except:  # skipcq: FLK-E722
            raise ImageProcessingError()

        try:
            img.seek(img.tell() + 1)
        except EOFError:
            frames[-1] = func(img)
            break

    return frames


def get_frames(img):
    return fixed_gif_frames(img)


def convert_frames(img, mode='RGBA'):
    def func(img):
        return img.convert(mode)

    return fixed_gif_frames(img, func)


def resize_gif(img, size, get_raw=True, **kwargs) -> BytesIO | Image.Image:
    frames = [resize_keep_aspect_ratio(frame, size, **kwargs)
              for frame in ImageSequence.Iterator(img)]


    if len(frames) > 200:
        raise TooManyFrames('Maximum amount of frames is 200')

    data = BytesIO()
    duration = get_duration(frames)
    frames[0].info['duration'] = duration
    frames[0].save(data, format='GIF', duration=duration, save_all=True, append_images=frames[1:], loop=65535)
    data.seek(0)
    if not get_raw:
        data = Image.open(data)

    return data


def func_to_gif(img, f, get_raw=True):
    if max(img.size) > 600:
        frames = [resize_keep_aspect_ratio(frame.convert('RGBA'), (600, 600), can_be_bigger=False, resample=Image.BILINEAR)
                  for frame in ImageSequence.Iterator(img)]
    else:
        frames = [frame.convert('RGBA') for frame in ImageSequence.Iterator(img)]

    if len(frames) > 150:
        raise TooManyFrames('Maximum amount of frames is 100')

    images = []
    for frame in frames:
        images.append(f(frame))

    data = BytesIO()
    duration = get_duration(frames)
    images[0].info['duration'] = duration
    images[0].save(data, format='GIF', duration=duration, save_all=True, append_images=images[1:], loop=65535)
    data.seek(0)
    if not get_raw:
        data = Image.open(data)

    return data


def gradient_flash(im, get_raw=True, transparency=None):
    """
    When get_raw is True gif is optimized with magick fixing some problems that PIL
    creates. It is the suggested method of using this funcion
    """

    frames = []
    if max(im.size) > 600:
        def f(frame):
            return resize_keep_aspect_ratio(frame.convert('RGBA'), (600, 600), can_be_bigger=False, resample=Image.BILINEAR)
    else:
        def f(frame):
            return frame.convert('RGBA')

    while True:
        frames.append(f(im))
        if len(frames) > 150:
            raise TooManyFrames('fuck this')
        try:
            im.seek(im.tell() + 1)
        except EOFError:
            frames[-1] = f(im)
            break

    if transparency is None and im.mode == 'RGBA' or im.info.get('background', None) is not None or im.info.get('transparency', None) is not None:
        transparency = True

    extended = 1
    while len(frames) <= 20:
        frames.extend([frame.copy() for frame in frames])
        extended += 1

    gradient = Color('red').range_to('#ff0004', len(frames))
    frames_ = zip(frames, gradient)
    images = []
    try:
        for frame in frames_:
            frame, g = frame
            img = Image.new('RGBA', im.size, tuple(map(lambda v: int(v*255), g.get_rgb())))
            img = ImageChops.multiply(frame, img)
            if transparency:
                # Use a mask to map the transparent area in the gif frame
                # optimize MUST be set to False when saving or transparency
                # will most likely be broken
                # source http://www.pythonclub.org/modules/pil/convert-png-gif
                alpha = img.split()[3]
                img = img.convert('P', palette=Image.ADAPTIVE, colors=255)
                mask = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
                img.paste(255, mask=mask)
                img.info['transparency'] = 255
                img.info['background'] = 255
            images.append(img)
    except Exception as e:
        logger.exception('{} Failed to create gif'.format(e))

    data = BytesIO()
    if isinstance(frames[0].info.get('duration', None), list):
        duration = frames[0].info['duration']
        for _ in range(1, extended):
            duration.extend(duration)
    else:
        duration = [frame.info.get('duration', 20) for frame in frames]

    images[0].save(data, format='gif', duration=duration, save_all=True, append_images=images[1:], loop=65535, disposal=2, optimize=True)

    data.seek(0)
    if get_raw:
        pass
    else:
        data = Image.open(data)

    return data


def apply_transparency(frames):
    im = frames[0]
    transparency = False
    if im.mode == 'RGBA' or im.info.get('background', None) is not None or im.info.get('transparency', None) is not None:
        transparency = True

    if not transparency:
        return frames

    images = []
    for img in frames:
        # Use a mask to map the transparent area in the gif frame
        # optimize MUST be set to False when saving or transparency
        # will most likely be broken
        # source http://www.pythonclub.org/modules/pil/convert-png-gif
        alpha = img.split()[3]
        img = img.convert('P', palette=Image.ADAPTIVE, colors=255)
        mask = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
        img.paste(255, mask=mask)
        img.info['transparency'] = 255
        img.info['background'] = 255
        images.append(img)

    return images


def concatenate_images(images, width=50):
    max_width = width*len(images)
    height = max(map(lambda i: i.height, images))

    empty = Image.new('RGBA', (max_width, height), (0,0,0,0))

    offset = 0
    for im in images:
        empty.paste(im, (offset, 0))
        offset += width

    return empty


def stack_images(images, height=50, max_width: int=None):
    max_height = height*len(images)
    if not max_width:
        max_width = max(map(lambda i: i.width, images))

    empty = Image.new('RGBA', (max_width, max_height), (0,0,0,0))

    offset = 0
    for im in images:
        empty.paste(im, (0, offset))
        offset += height

    return empty
