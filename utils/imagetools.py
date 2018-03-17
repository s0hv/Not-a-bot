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

import hashlib
import logging
import os
import subprocess
from io import BytesIO
from shlex import split
from sys import platform
from threading import Lock

import aiohttp
import geopatterns
import magic
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageSequence
from colorthief import ColorThief as CF
from colour import Color
from geopatterns import svg
from geopatterns.utils import promap
from numpy import sqrt

#import cv2
cv2 = None  # Remove cv2 import cuz it takes forever to import

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')
IMAGES_PATH = os.path.join(os.getcwd(), 'data', 'images')
MAGICK = 'magick '
try:
    subprocess.call(['magick'], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except:
    MAGICK = ''

MAX_COLOR_DIFF = 2.82842712475  # Biggest value produced by color_distance
GLOW_LOCK = Lock()
TRIMMING_LOCK = Lock()
if not os.path.exists(IMAGES_PATH):
    os.mkdir(IMAGES_PATH)


def make_shiftable(color):
    # Color stays almost the same when it's too close to white or black
    max_dist = MAX_COLOR_DIFF * 0.05
    if color_distance(color, Color('white')) < max_dist:
        color.set_hex('#EEEEEE')
    elif color_distance(color, Color('black')) < max_dist:
        color.set_hex('#333333')

    return color


class ColorThief(CF):
    def __init__(self, img):
        if isinstance(img, Image.Image):
            self.image = img
        else:
            self.image = Image.open(img)


class GeoPattern(geopatterns.GeoPattern):
    # 'triangles' removed cuz it doesn't work
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
        'xes'
    ]

    def __init__(self, string, generator, color=None):
        self.hash = hashlib.sha1(string.encode('utf8')).hexdigest()
        self.svg = svg.SVG()
        self.base_color = color

        if generator not in self.available_generators:
            raise ValueError('{} is not a valid generator. Valid choices are {}.'.format(
                generator, ', '.join(['"{}"'.format(g) for g in self.available_generators])
            ))
        self.generate_background(color=color)
        getattr(self, 'geo_%s' % generator)()

    def generate_background(self, color=None):
        if isinstance(color, Color):
            base_color = color
        elif isinstance(color, str):
            base_color = Color(color)
        else:
            base_color = Color(hsl=(0, .42, .41))
            hue_offset = promap(int(self.hash[14:][:3], 16), 0, 4095, 0, 365)
            base_color.hue = base_color.hue - hue_offset

        base_color = make_shiftable(base_color)
        sat_offset = promap(int(self.hash[17:][:1], 16), 0, 15, 0, 0.5)

        if sat_offset % 2:
            base_color.saturation = min(base_color.saturation + sat_offset, 1.0)
        else:
            base_color.saturation = max(abs(base_color.saturation - sat_offset), 0.0)
        rgb = base_color.rgb
        r = int(round(rgb[0] * 255))
        g = int(round(rgb[1] * 255))
        b = int(round(rgb[2] * 255))
        self.base_color = base_color
        return self.svg.rect(0, 0, '100%', '100%', **{
            'fill': 'rgb({}, {}, {})'.format(r, g, b)
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
    red, green, blue, alpha = data.T  # Temporarily unpack the bands for readability

    r,g,b = color1
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
    svg = os.path.join(IMAGES_PATH, 'bg.svg')

    args = '{}convert -size 100x100 svg:- png:-'.format(MAGICK)
    p = subprocess.Popen(args.split(' '), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p.stdin.write(pattern.svg_string.encode('utf-8'))
    out, err = p.communicate()
    buff = BytesIO(out)
    img = Image.open(buff)
    img = bg_from_texture(img, size)
    return img, Color(pattern.base_color)


# http://stackoverflow.com/a/29314286/6046713
# http://stackoverflow.com/a/41048793/6046713
def remove_background(image, blur=21, canny_thresh_1=10, canny_thresh_2=50,
                      mask_dilate_iter=5, mask_erode_iter=5):
    global cv2
    if cv2 is None:
        try:
            import cv2
        except ImportError:
            cv2 = None

    if cv2 is None:
        return image

    # Parameters
    BLUR = blur
    CANNY_THRESH_1 = canny_thresh_1
    CANNY_THRESH_2 = canny_thresh_2
    MASK_DILATE_ITER = mask_dilate_iter
    MASK_ERODE_ITER = mask_erode_iter

    p = os.path.join(IMAGES_PATH, 'trimmed.png')
    with TRIMMING_LOCK:
        try:
            image.save(p)
            # Processing
            # Read image
            if platform == 'win32':
                p = p.replace('\\', '/')  # Windows paths don't work in cv2

            img = cv2.imread(p)
        except:
            return image

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Edge detection
    edges = cv2.Canny(gray, CANNY_THRESH_1, CANNY_THRESH_2)
    edges = cv2.dilate(edges, None)
    edges = cv2.erode(edges, None)

    # Find contours in edges, sort by area
    contour_info = []
    _, contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    for c in contours:
        contour_info.append((
            c,
            cv2.isContourConvex(c),
            cv2.contourArea(c),
        ))
    contour_info = sorted(contour_info, key=lambda c: c[2], reverse=True)
    max_contour = contour_info[0]

    # Create empty mask, draw filled polygon on it corresponding to largest contour
    # Mask is black, polygon is white
    mask = np.zeros(edges.shape)
    cv2.fillConvexPoly(mask, max_contour[0], (255))

    # Smooth mask, then blur it
    mask = cv2.dilate(mask, None, iterations=MASK_DILATE_ITER)
    mask = cv2.erode(mask, None, iterations=MASK_ERODE_ITER)
    mask = cv2.GaussianBlur(mask, (BLUR, BLUR), 0)

    img = img.astype('float32') / 255.0  # for easy blending

    # split image into channels
    c_red, c_green, c_blue = cv2.split(img)

    # merge with mask got on one of a previous steps
    img_a = cv2.merge((c_red, c_green, c_blue, mask.astype('float32') / 255.0))

    r, buf = cv2.imencode('.png', img_a * 255)
    buffer = BytesIO(bytearray(buf))
    return Image.open(buffer)


async def image_from_url(url, client):
    return Image.open(await raw_image_from_url(url, client))


async def raw_image_from_url(url, client, get_mime=False):
    data = None
    mime_type = None
    try:
        async with client.get(url) as r:
            terminal.debug('Downloading image url {}'.format(url))
            if not r.headers.get('Content-Type', '').startswith('image'):
                raise TypeError

            max_size = 8000000
            size = int(r.headers.get('Content-Length', 0))
            if size > max_size:
                raise OverflowError

            data = BytesIO()
            chunk = 4096
            total = 0
            async for d in r.content.iter_chunked(chunk):
                if total == 0:
                    mime_type = magic.from_buffer(d, mime=True)
                    total += chunk
                    if not mime_type.startswith('image') and mime_type != 'application/octet-stream':
                        raise TypeError

                total += chunk
                if total > max_size:
                    raise OverflowError

                data.write(d)
        data.seek(0)
    except aiohttp.ClientError:
        logger.exception('Could not download image %s' % url)
        if get_mime:
            return None, None
        return None

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
            terminal.exception('Could not create glow')
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


def resize_keep_aspect_ratio(img, new_size, crop_to_size=False, can_be_bigger=True,
                             center_cropped=False, background_color=None,
                             resample=Image.NEAREST):
    """
    Args:
        img: Image to be cropped
        new_size: Size of the new image
        crop_to_size: after resizing crop image so it's exactly the specified size
        can_be_bigger: Tells if the image can be bigger than the requested size
        center_cropped: Center the image. Used in combination with crop_to_size
                        since otherwise the added or removed space will only be in the
                        bottom right corner
        background_color: Color of the background
        resample: The type of resampling to use

    Returns:
        Image.Image
    """
    x, y = img.size
    x_m = x / new_size[0]
    y_m = y / new_size[1]
    check = y_m <= x_m if can_be_bigger else y_m >= x_m
    if check:
        m = new_size[1] / y
    else:
        m = new_size[0] / x

    img = img.resize((int(x * m), int(y * m)), resample=resample)
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


def gradient_flash(im, get_raw=True):
    """
    When get_raw is True gif is optimized with magick fixing some problems that PIL
    creates. It is the suggested method of using this funcion
    """
    if max(im.size) > 600:
        frames = [resize_keep_aspect_ratio(frame.convert('RGBA'), (600, 600), can_be_bigger=False, resample=Image.BILINEAR)
                  for frame in ImageSequence.Iterator(im)]
    else:
        frames = [frame.convert('RGBA') for frame in ImageSequence.Iterator(im)]

    while len(frames) <= 25:
        frames.extend([frame.copy() for frame in frames])

    gradient = Color('red').range_to('#ff0004', len(frames))
    frames_ = zip(frames, gradient)

    images = []
    try:
        for frame in frames_:
            frame, g = frame
            img = Image.new('RGBA', im.size, tuple(map(lambda v: int(v*255), g.get_rgb())))
            img = ImageChops.multiply(frame, img)
            img = Image.composite(img, frame, frame)
            images.append(img)
    except Exception as e:
        logger.exception('{} Failed to create gif'.format(e))

    data = BytesIO()
    if isinstance(frames[0].info.get('duration', None), list):
        duration = frames[0].info['duration']
    else:
        duration = [frame.info.get('duration', 20) for frame in frames]

    images[0].info['duration'] = duration
    images[0].save(data, format='GIF', duration=duration, save_all=True, append_images=images[1:], loop=65535)

    data.seek(0)
    if get_raw:
        data = optimize_gif(data.getvalue())
    else:
        data = Image.open(data)

    return data


def optimize_gif(gif_bytes):
    cmd = '{}convert - -dither none -deconstruct -layers optimize -matte -depth 8 gif:-'.format(MAGICK)
    p = subprocess.Popen(split(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p.stdin.write(gif_bytes)
    out, err = p.communicate()
    buff = BytesIO(out)
    return buff
