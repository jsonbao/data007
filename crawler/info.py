#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" borrow almost all codes from python-rq """
import os
import sys
import time
import logging
import argparse

from queues import ai1, ai2, as1, af1, asi1
from caches import LC, WC

from settings import RECORD_URI
import re
import redis
from datetime import datetime
host, port, db = re.compile('redis://(.*):(\d+)/(\d+)').search(RECORD_URI).groups()
conn = redis.Redis(host=host, port=int(port), db=int(db))
def get_counts(date = None):
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    counts = conn.hgetall(date)
    counts['time'] = time.time()
    return counts

last_counts = {}
def get_throughput():
    global last_counts
    if last_counts == {}:
        last_counts = get_counts()
        return {}
    else:
        throughput = {}
        current_counts = get_counts()
        time_passed = current_counts['time'] - last_counts['time']
        for key in ['item:crawl-success', 'item:crawl-err-except', 'item:crawl-data-err']:
            throughput[key] = (int(current_counts.get(key, '0')) -
                                int(last_counts.get(key, '0'))) / time_passed
        last_counts = current_counts
        return throughput

def gettermsize():
    """ get console window width in python """
    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct  # noqa
            cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ,
        '1234'))
        except:
            return None
        return cr
    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass
    if not cr:
        try:
            cr = (os.environ['LINES'], os.environ['COLUMNS'])
        except:
            cr = (25, 80)
    return int(cr[1]), int(cr[0])


class _Colorizer(object):
    def __init__(self):
        esc = "\x1b["

        self.codes = {}
        self.codes[""] = ""
        self.codes["reset"] = esc + "39;49;00m"

        self.codes["bold"] = esc + "01m"
        self.codes["faint"] = esc + "02m"
        self.codes["standout"] = esc + "03m"
        self.codes["underline"] = esc + "04m"
        self.codes["blink"] = esc + "05m"
        self.codes["overline"] = esc + "06m"

        dark_colors = ["black", "darkred", "darkgreen", "brown", "darkblue",
                        "purple", "teal", "lightgray"]
        light_colors = ["darkgray", "red", "green", "yellow", "blue",
                        "fuchsia", "turquoise", "white"]

        x = 30
        for d, l in zip(dark_colors, light_colors):
            self.codes[d] = esc + "%im" % x
            self.codes[l] = esc + "%i;01m" % x
            x += 1

        del d, l, x

        self.codes["darkteal"] = self.codes["turquoise"]
        self.codes["darkyellow"] = self.codes["brown"]
        self.codes["fuscia"] = self.codes["fuchsia"]
        self.codes["white"] = self.codes["bold"]

        if hasattr(sys.stdout, "isatty"):
            self.notty = not sys.stdout.isatty()
        else:
            self.notty = True

    def reset_color(self):
        return self.codes["reset"]

    def colorize(self, color_key, text):
        if not sys.stdout.isatty():
            return text
        else:
            return self.codes[color_key] + text + self.codes["reset"]

    def ansiformat(self, attr, text):
        """
        Format ``text`` with a color and/or some attributes::

            color       normal color
            *color*     bold color
            _color_     underlined color
            +color+     blinking color
        """
        result = []
        if attr[:1] == attr[-1:] == '+':
            result.append(self.codes['blink'])
            attr = attr[1:-1]
        if attr[:1] == attr[-1:] == '*':
            result.append(self.codes['bold'])
            attr = attr[1:-1]
        if attr[:1] == attr[-1:] == '_':
            result.append(self.codes['underline'])
            attr = attr[1:-1]
        result.append(self.codes[attr])
        result.append(text)
        result.append(self.codes['reset'])
        return ''.join(result)


colorizer = _Colorizer()


def make_colorizer(color):
    """Creates a function that colorizes text with the given color.

    For example:

        green = make_colorizer('darkgreen')
        red = make_colorizer('red')

    Then, you can use:

        print "It's either " + green('OK') + ' or ' + red('Oops')
    """
    def inner(text):
        return colorizer.colorize(color, text)
    return inner


class ColorizingStreamHandler(logging.StreamHandler):

    levels = {
        logging.WARNING: make_colorizer('darkyellow'),
        logging.ERROR: make_colorizer('darkred'),
        logging.CRITICAL: make_colorizer('darkred'),
    }

    def __init__(self, exclude=None, *args, **kwargs):
        self.exclude = exclude
        if is_python_version((2,6)):
            logging.StreamHandler.__init__(self, *args, **kwargs)
        else:
            super(ColorizingStreamHandler, self).__init__(*args, **kwargs)

    @property
    def is_tty(self):
        isatty = getattr(self.stream, 'isatty', None)
        return isatty and isatty()

    def format(self, record):
        message = logging.StreamHandler.format(self, record)
        if self.is_tty:
            colorize = self.levels.get(record.levelno, lambda x: x)

            # Don't colorize any traceback
            parts = message.split('\n', 1)
            parts[0] = " ".join([parts[0].split(" ", 1)[0], colorize(parts[0].split(" ", 1)[1])])

            message = '\n'.join(parts)

        return message

red = make_colorizer('darkred')
green = make_colorizer('darkgreen')
yellow = make_colorizer('darkyellow')

def pad(s, pad_to_length):
    """Pads the given string to the given length."""
    return ('%-' + '%ds' % pad_to_length) % (s,)


def get_scale(x):
    """Finds the lowest scale where x <= scale."""
    scales = [20, 50, 100, 200, 400, 600, 800, 1000]
    for scale in scales:
        if x <= scale:
            return scale
    return x


def state_symbol(state):
    symbols = {
        'busy': red('busy'),
        'idle': green('idle'),
    }
    try:
        return symbols[state]
    except KeyError:
        return state


def show_queues(args):
    qs = [ai1, ai2, as1, af1, asi1]
    num_jobs = 0
    termwidth, _ = gettermsize()
    chartwidth = min(20, termwidth - 20)

    max_count = 0
    counts = dict()
    for q in qs:
        count = q.qsize()
        counts[q.key] = count
        max_count = max(max_count, count)

    scale = get_scale(max_count)
    ratio = chartwidth * 1.0 / scale

    print('Queues Info:')
    for q in qs:
        count = counts[q.key]
        chart = green('|' + '█' * int(ratio * count))
        line = '    %-12s %s %d' % (q.key, chart, count)
        print(line)

        num_jobs += count

    tp = get_throughput()
    if tp:
        print('\nThroughputs:')
        for key in tp:
            print('    {}: {:4.2f}/s'.format(key, tp[key]))
    print('')


def show_counts(args):
    num_items = 0
    termwidth, _ = gettermsize()
    chartwidth = min(20, termwidth - 20)

    types = ['item', 'shop', 'shopinfo']

    max_count = 0
    counts = dict()
    for t in types:
        count = LC.count(t)
        counts[t] = count
        max_count = max(max_count, count)

    scale = get_scale(max_count)
    ratio = chartwidth * 1.0 / scale

    print('Counts Info:')
    for t in types:
        count = counts[t]
        chart = green('|' + '█' * int(ratio * count))
        line = '    %-12s %s %d' % (t, chart, count)
        print(line)

        num_items += count

    chart = green('|' + '█' * int(ratio * WC.count()))
    line = '    %-12s %s %d' % ('items(wrong cate)', chart, WC.count())
    print(line)

def show_both(args):
    show_queues(args)
    show_counts(args)

def parse_args():
    parser = argparse.ArgumentParser(description='ataobao command-line monitor.')
    parser.add_argument('--interval', '-i', metavar='N', type=float, default=2.5, help='Updates stats every N seconds (default: don\'t poll)')
    return parser.parse_args()


def interval(val, func, args):
    while True:
        if val and sys.stdout.isatty():
            os.system('clear')
        func(args)
        if val and sys.stdout.isatty():
            time.sleep(val)
        else:
            break

def main():
    args = parse_args()

    try:
        func = show_both
        interval(args.interval, func, args)
    except KeyboardInterrupt:
        print
        sys.exit(0)

if __name__ == '__main__':
    main()
