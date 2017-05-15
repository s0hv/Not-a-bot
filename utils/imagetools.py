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
import os
import subprocess

import geopatterns
from PIL import Image, ImageChops, ImageDraw
from colorthief import ColorThief as CF
from colour import Color
from geopatterns import svg
from geopatterns.utils import promap
from numpy import sqrt
import numpy as np
import cv2
import logging
from threading import Lock
from sys import platform
from io import BytesIO

logger = logging.getLogger('debug')
IMAGES_PATH = os.path.join(os.getcwd(), 'data', 'images')
MAGICK = 'magick'
try:
    subprocess.call('magick')
except:
    MAGICK = ''

MAX_COLOR_DIFF = 2.82842712475  # Biggest value produced by color_distance
GLOW_LOCK = Lock()
TRIMMING_LOCK = Lock()
if not os.path.exists(IMAGES_PATH):
    #os.mkdir(IMAGES_PATH)
    pass


class ColorThief(CF):
    def __init__(self, img):
        if isinstance(img, Image.Image):
            self.img = img
        else:
            self.img = Image.open(img)


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


def get_palette(img, colors=6, quality=5):
    cf = ColorThief(img)
    return cf.get_palette(colors, quality=quality)


def create_geopattern_background(size, s, color=None, generator='overlapping_circles'):
    pattern = GeoPattern(s, generator=generator, color=color)
    svg = os.path.join(IMAGES_PATH, 'bg.svg')

    args = 'magick convert -size 100x100 svg:- png:-'
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
                      mask_dilate_iter=10, mask_erode_iter=10):
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
    try:
        async with client.get(url) as r:
            data = BytesIO()
            async for d in r.content.iter_chunked(4096):
                data.write(d)
            img = Image.open(data)
    except:
        logger.exception('Could not download image %s' % url)
        return None

    return img


def shift_color(color, amount):
    if amount == 0:
        return color

    def shift_value(val):
        if val <= 0.5:
            return val * 0.035 * (1 + (amount/20))
        else:
            return val * 0.035 * (1 - (amount/20))

    # Color stays almost the same when it's too close to white or black
    max_dist = MAX_COLOR_DIFF * 0.05
    if color_distance(color, Color('white')) < max_dist:
        color.set_hex('#EEEEEE')
    elif color_distance(color, Color('black')) < max_dist:
        color.set_hex('#333333')

    sat = color.saturation
    hue = color.hue
    if round(hue, 3) == 0:
        hue = 200

    if round(sat, 3) == 0:
        sat = 0.1

    print(hue, sat)
    color.saturation = min(abs(sat * (1 + amount/20)), 1.0)
    color.hue = shift_value(hue)
    print(color.get_hue())
    print(color.get_saturation())

    return color


def create_glow(img, amount):
    image_path = os.path.join(IMAGES_PATH, 'text.png')
    glow_path = os.path.join(IMAGES_PATH, 'glow.png')

    with GLOW_LOCK:
        try:
            img.save(image_path, 'PNG')
            args = 'magick convert {} -blur 0x{} {}'.format(image_path, amount, glow_path)
            subprocess.call(args.split(' '))
            args = 'magick composite -compose multiply {} {} png:-'.format(glow_path, image_path)
            p = subprocess.Popen(args.split(' '), stdout=subprocess.PIPE)
            out = p.stdout.read()
            buff = BytesIO(out)
        except Exception:
            print('[ERROR] Could not create glow')
            return img

    return Image.open(buff)


def create_shadow(img, percent, opacity, x, y):
    import shlex
    args = 'magick convert - ( +clone -background black -shadow {}x{}+{}+{} ) +swap ' \
           '-background transparent -layers merge +repage png:-'.format(percent, opacity, x, y)
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


def resize_keep_aspect_ratio(img, new_size):
    x, y = img.size
    x_m = x / new_size[0]
    y_m = y / new_size[1]
    if y_m >= x_m:
        m = new_size[1] / y
    else:
        m = new_size[0] / x

    return img.resize((int(x * m), int(y * m)))


def create_text(s, font, fill, canvas_size, point=(10, 10)):
    text = Image.new('RGBA', canvas_size)
    draw = ImageDraw.Draw(text)
    draw.text(point, s, fill, font=font)
    return text
