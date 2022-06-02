import gi
gi.require_version('Gst', '1.0')

from gi.repository import GLib, GObject, Gst
Gst.init(None)

import click
from datetime import datetime, timedelta
import httpcore
import itertools
import json
from mimetypes import guess_type
import os
from lib.pn532 import *
import pylast
import RPi.GPIO as GPIO
from select import select
import sys
import termios
import threading
import time
from tinytag import TinyTag
import tty
from deck.redis import Redis


class PlayerErrors:
    def error(self, text):
        width = os.get_terminal_size()[0]
        print('\r**', text.ljust(width - 1), end='\r\n')


class Player(PlayerErrors):
    def __init__(self, loop):
        self.player = Gst.ElementFactory.make('playbin', 'player')
        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)
        self.state = Gst.State.NULL
        self.loop = loop
        self.redis = Redis()
        self.restore_state()
        self.spinner = itertools.cycle(['⠇', '⠏', '⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧'])
        self.original_terminal_state = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.STATE_CHANGED:
            state = message.parse_state_changed()[1]
            if state != self.state:
                self.state = state
        elif message.type == Gst.MessageType.EOS:
            self.player_state(Gst.State.NULL)
            self.playing = False
        elif message.type == Gst.MessageType.ERROR:
            self.player_state(Gst.State.NULL)
            err, debug = message.parse_error()
            self.error('error "%s" "%s"' % (err, debug))
            self.playing = False
        elif message.type in [
            Gst.MessageType.ASYNC_DONE,
            Gst.MessageType.DURATION_CHANGED,
            Gst.MessageType.LATENCY,
            Gst.MessageType.NEW_CLOCK,
            Gst.MessageType.RESET_TIME,
            Gst.MessageType.STREAM_START,
            Gst.MessageType.STREAM_STATUS,
            Gst.MessageType.TAG,
        ]:
            pass
        else:
            self.error('unknown message type "%s"' % message.type)

    def play(self, file):
        track = os.path.realpath(file)
        tags = TinyTag.get(track)
        self.play_track({'file': track, 'tags': tags.as_dict()})
        self.quit()

    def spin(self):
        print('[Space]:pause/play  [L]:fast-fwd    [J]:rewind      [1234567890]:position', end='\r\n')
        print('[N]:next track      [P]:prev track  [X]:skip track  [S]:stop', end='\r\n')
        print('[Q/+]:vol up        [A/-]:vol down  [M]:mute        [^C]:quit', end='\r\n\n')
        while True:
            if self.state == 'stopped':
                char = self.wait_for_key(timeout=0.2)
                if char and ord(char) == 32:
                    self.player_state(Gst.State.NULL)
            else:
                track = self.redis.lindex('queue', 0)
                if track:
                    track = track.decode()
                    self.redis.lpop('queue')
                    self.play_track(json.loads(track))
                    if self.get_state() == 'stopped':
                        self.redis.lpush('queue', track)
                    elif self.get_state() not in ['skipped', 'previous']:
                        self.redis.lpush('recently_played', track)
                        self.redis.ltrim('recently_played', 0, 99)
                else:
                    char = self.wait_for_key(timeout=0.2)
                    if char:
                        if ord(char) in [3, 28]:
                            self.quit()
                        elif char in ['q', 'Q']:
                            self.adjust_volume(50)
                        elif char in ['a', 'A']:
                            self.adjust_volume(-50)
                        elif char in ['m', 'M']:
                            self.toggle_mute()
            self.check_for_command()
            self.output_player_state()

    def play_track(self, track):
        if os.path.isfile(track['file']):
            self.redis.set('current_track', json.dumps(track))
            self.output_text_state(format_track_text(track, flag='-'))
            self.player.set_property('uri', 'file://' + track['file'])
            self.player_state(Gst.State.PLAYING)
            started = datetime.now().timestamp()
            self.playing = True
            while self.playing:
                # check for keypress with 1/10th of a second timeout
                # so the progress bar gets refreshed regularly
                char = self.wait_for_key(timeout=0.1)
                if char:
                    if ord(char) in [3, 28]:
                        self.quit()
                    elif ord(char) == 32:
                        self.pause_or_resume()
                        self.redis.set('current_track', json.dumps(track))
                    elif char in ['j', 'J']:
                        self.relative_seek(-15)
                    elif char in ['l', 'L']:
                        self.relative_seek(15)
                    elif char in ['q', 'Q', '=', '+']:
                        self.adjust_volume(50)
                    elif char in ['a', 'A', '-', '_']:
                        self.adjust_volume(-50)
                    elif char in ['m', 'M']:
                        self.toggle_mute()
                    elif char in ['s', 'S']:
                        self.stop()
                    elif char in ['x', 'X']:
                        self.skip()
                    elif char in ['n', 'N']:
                        self.next_track()
                    elif char in ['p', 'P']:
                        self.previous_track()
                    elif ord(char) in range(48, 58):
                        self.set_position(char)
                self.check_for_command()
                self.output_player_state()
            self.redis.delete('current_track')
            if self.get_state() != 'skipped':
                self.scrobble(track, started)
        else:
            self.output_text_state('** missing file "%s"' % track)

    def wait_for_key(self, timeout=1):
        char = None
        ready, _, _ = select([sys.stdin], [], [], timeout)
        for stream in ready:
            if stream == sys.stdin:
                char = sys.stdin.read(1)
        return char

    def check_for_command(self):
        command = self.redis.getdel('command')
        if command:
            if command.decode() == 'pause':
                self.pause_or_resume()
            elif command.decode() == 'next':
                self.next_track()
            elif command.decode() == 'previous':
                self.previous_track()
            elif command.decode() == 'stop':
                self.stop()
            elif command.decode() == 'skip':
                self.skip()
            elif command.decode() == 'quit':
                self.quit()
            else:
                self.error('unknown command "%s" received' % command)

    def pause_or_resume(self):
        if self.state in [Gst.State.PLAYING, 'seek_forwards', 'seek_backwards']:
            self.player_state(Gst.State.PAUSED)
            self.relative_seek(-0.05, show_state=False)
        elif self.state in [Gst.State.PAUSED, 'stopped']:
            self.player_state(Gst.State.PLAYING)
        time.sleep(0.1)

    def stop(self):
        self.redis.delete('current_track')
        self.player_state(Gst.State.NULL, 'stopped')
        self.playing = False

    def skip(self):
        self.redis.delete('current_track')
        self.player_state(Gst.State.NULL, 'skipped')
        self.playing = False

    def next_track(self):
        self.redis.delete('current_track')
        self.player_state(Gst.State.PAUSED)
        self.player_state(Gst.State.NULL)
        self.playing = False

    def previous_track(self):
        self.redis.delete('current_track')
        track = self.redis.lpop('recently_played')
        self.redis.lpush('queue', track)
        self.player_state(Gst.State.PAUSED)
        self.player_state(Gst.State.NULL, 'previous')
        self.playing = False

    def player_state(self, state, store=None):
        self.player.set_state(state)
        if not store:
            self.state = state
            if state == Gst.State.PLAYING:
                store = 'playing'
            elif state == Gst.State.PAUSED:
                store = 'paused'
            elif state == Gst.State.NULL:
                store = 'null'
            else:
                self.error('unknown state "%s" to store' % state)
        else:
            self.state = store
        self.redis.set('state', store)

    def get_state(self):
        state = self.redis.get('state')
        if state:
            return state.decode()
        return None

    def relative_seek(self, amount=0, show_state=True):
        position = self.player.query_position(Gst.Format.TIME)[1]
        duration = self.player.query_duration(Gst.Format.TIME)[1]
        seek = position + (amount * 1000000000)

        if show_state:
            self.state = 'seek_forwards'
            if amount < 0:
                self.state = 'seek_backwards'
            self.output_player_state()

        self.player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH,
            min(max(seek, 0), duration),
        )

        if show_state:
            # allow a small amount of time for the seek
            # indicator to remain on screen
            time.sleep(0.2)

    def set_position(self, position):
        position = int(position) - 1
        if position < 0:
            position = 9
        duration = self.player.query_duration(Gst.Format.TIME)[1]
        seek = 0 + (duration * (position / 10))
        self.player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH,
            min(max(seek, 0), duration),
        )
        time.sleep(0.1)

    def adjust_volume(self, adjustment):
        volume = (self.player.get_property('volume') * 1000) + adjustment
        self.set_volume(volume)

    def set_volume(self, volume):
        volume = min(max(int(volume), 0), 1000)
        actual = volume / 1000
        self.player.set_property('volume', actual)
        self.redis.set('volume', volume)
        self.unmute()

    def toggle_mute(self):
        if self.player.get_property('mute'):
            self.unmute()
        else:
            self.mute()

    def mute(self):
        self.player.set_property('mute', True)
        self.redis.set('muted', 1)

    def unmute(self):
        self.player.set_property('mute', False)
        self.redis.set('muted', 0)

    def output_text_state(self, text):
        print(text.ljust(79), end='\r\n', flush=True)

    def output_player_state(self):
        progress_bar_width = 44
        if os.get_terminal_size()[0] > 80:
            progress_bar_width = os.get_terminal_size()[0] - 36

        duration = self.player.query_duration(Gst.Format.TIME)[1]
        position = self.player.query_position(Gst.Format.TIME)[1]
        if duration < 0 or position < 0:
            # unintialised state, no times
            duration_time = '--:--'
            position_time = '--:--'
            progress_bar = '_' * progress_bar_width
        else:
            progress = int((position / duration) * progress_bar_width)
            progress_bar = (('_' * (progress-1)) + 'V').ljust(progress_bar_width, '_')
            position_time = self.minutes_seconds(position)
            duration_time = self.minutes_seconds(duration)

        volume_bar_width = 10
        volume = int(round(self.player.get_property('volume'), 1) * 10)
        volume_bar = ('=' * volume).ljust(volume_bar_width)

        if self.player.get_property('mute'):
            volume_bar = volume_bar[0:3] + ' XX ' + volume_bar[7:10]

        if self.state == Gst.State.PLAYING:
            state = '▶'
        elif self.state == Gst.State.PAUSED:
            state = '‖'
        elif self.state == 'seek_forwards':
            state = '→'
        elif self.state == 'seek_backwards':
            state = '←'
        elif self.state == 'stopped':
            state = '◼'
        elif self.state in [Gst.State.NULL, 'skipped']:
            state = next(self.spinner)
        else:
            state = '?'

        # 12345678901234567890123456789012345678901234567890123456789012345678901234567890
        #   ▶  [==========]   00:04 [______|_____________________________________] 00:31
        print(
            f"  {state}  [{volume_bar}]   {position_time} [{progress_bar}] {duration_time}",
            end='\r',
            flush=True,
        )

    def scrobble(self, track, started):
        track['started'] = started
        self.redis.rpush('scrobble_queue', json.dumps(track))

    def restore_state(self):
        volume = self.redis.get('volume')
        if volume:
            self.set_volume(volume)
        else:
            self.set_volume(1000)
        mute = self.redis.get('muted')
        if mute:
            if int(mute) == 1:
                self.mute()
            else:
                self.unmute()
        was_playing = self.redis.get('current_track')
        if was_playing:
            self.redis.lpush('queue', was_playing.decode())

    def minutes_seconds(self, t):
        s,ns = divmod(t, 1000000000)
        m,s = divmod(s, 60)
        return "%02i:%02i" % (m,s)

    def quit(self):
        termios.tcsetattr(
            sys.stdin.fileno(),
            termios.TCSANOW,
            self.original_terminal_state,
        )
        print()
        self.loop.quit()
        sys.exit()


class Scrobbler(PlayerErrors):
    def scrobble_plays(self):
        redis = Redis()
        try:
            self.lastfm = pylast.LastFMNetwork(
                api_key = os.environ['LASTFM_KEY'],
                api_secret = os.environ['LASTFM_SECRET'],
                username = os.environ['LASTFM_USER'],
                password_hash = pylast.md5(os.environ['LASTFM_PASS']),
            )
        except KeyError:
            self.error('LASTFM environment vars missing; scrobbling disabled.')
            self.lastfm = None

        if self.lastfm:
            current_track = None
            while True:
                current = redis.get('current_track')
                if current:
                    track = json.loads(current.decode())
                    if track != current_track:
                        current_track = track
                        self.scrobble_current(track)
                scrobble = redis.lindex('scrobble_queue', 0)
                if scrobble:
                    track = json.loads(scrobble)
                    self.scrobble_played(track)
                    redis.lpop('scrobble_queue')
                time.sleep(1)

    def scrobble_current(self, track):
        attempts = 3
        while attempts:
            try:
                self.lastfm.update_now_playing(
                    album = track['tags']['album'],
                    artist = track['tags']['artist'],
                    title = track['tags']['title'],
                )
                attempts = 0
            except httpcore.ConnectError as e:
                if e.errno == -3:
                    # temp failure, retry
                    time.sleep(5)
                    attempts = attempts - 1
                else:
                    raise

    def scrobble_played(self, track):
        attempts = 3
        while attempts:
            try:
                self.lastfm.scrobble(
                    album = track['tags']['album'],
                    artist = track['tags']['artist'],
                    title = track['tags']['title'],
                    # FIXME mbid if known
                    timestamp = track['started'],
                )
                attempts = 0
            except httpcore.ConnectError as e:
                # FIXME account for other network failures
                if e.errno == -3:
                    # temp failure, retry
                    time.sleep(5)
                    attempts = attempts - 1
                else:
                    raise


class NFCReader(PlayerErrors):
    def __init__(self):
        try:
            self.pn532 = PN532_UART(debug=False, reset=20)
            self.pn532.SAM_configuration()
            self.uart_found = True
        except:
            self.error('No NFC reader found')
            self.uart_found = False
        GPIO.cleanup()

    def listen(self):
        if not self.uart_found:
            return

        redis = Redis()
        last = {}
        while True:
            try:
                uid = self.pn532.read_passive_target(timeout=0.5)
            except RuntimeError as e:
                if 'Did not receive expected ACK' not in str(e):
                    self.error('NFC: %s' % e)
                uid = None

            if uid:
                playlist = 'nfc/%s.m3u' % bytes.hex(uid)
                try:
                    # don't retrigger from the same NFC (it is "seen" multiple
                    # times in quick succession if not moved away quickly)
                    if last[playlist] + timedelta(seconds=10) > datetime.now():
                        continue
                except KeyError:
                    pass
                clear_queue()
                skip_current_track()
                queue_file(playlist)
                last[playlist] = datetime.now()


def clear_queue():
    redis = Redis()
    redis.ltrim('queue', 1, 0)


def queue_file(file, prepend=False):
    redis = Redis()
    if os.path.exists(file):
        guessed_type = guess_type(file)[0]
        if guessed_type == 'audio/mpegurl':
            queue_playlist(file, prepend)
        elif guessed_type.startswith('audio/'):
            track = os.path.realpath(file)
            tags = TinyTag.get(track)
            if prepend:
                redis.lpush(
                    'queue',
                    json.dumps({'file': track, 'tags': tags.as_dict()}),
                )
            else:
                redis.rpush(
                    'queue',
                    json.dumps({'file': track, 'tags': tags.as_dict()}),
                )
        else:
            PlayerErrors().error('UNKNOWN FILE TYPE "%"' % file)
    else:
        PlayerErrors().error('NO FILE "%s"' % file)


def queue_playlist(file, prepend=False):
    tracks = []
    with open(file) as playlist:
        for line in playlist.readlines():
            if line.startswith('#'):
                continue
            tracks.append(line.strip())
    queue_files(tracks, prepend)


def queue_directory(dir, prepend=False):
    for root, dirs, files in os.walk(dir, topdown=True):
        dirs.sort(reverse=prepend)
        files.sort()
        queue_files([os.path.join(root, file) for file in files], prepend)


def queue_files(files, prepend=False):
    if files[0] == '-':
        files = [ line.rstrip() for line in sys.stdin ]
    if prepend:
        files = reversed(files)
    for file in files:
        if os.path.isdir(file):
            queue_directory(file, prepend)
        else:
            queue_file(file, prepend)


def shorten(text, target):
    if len(text) > target:
        text = text[0:target-1] + '…'
    return text.ljust(target)


def format_track_text(track, flag=None):
    try:
        width = os.get_terminal_size()[0]
    except OSError:
        width = 80
    avail = width - 14
    title_width = round(avail * 0.4)
    avail = avail - title_width
    album_width = round(avail * 0.5)
    artist_width = avail - album_width

    try:
        title = shorten(track['tags']['title'], title_width)
    except:
        title = 'Unknown Track'
    try:
        album = shorten(track['tags']['album'], album_width)
    except:
        album = 'Unknown Album'
    try:
        artist = shorten(track['tags']['artist'], artist_width)
    except:
        artist = 'Unknown Artist'
    try:
        num = int(track['tags']['track'])
        tracks = int(track['tags']['track_total'])
    except:
        num = 1
        tracks = 1

    if not flag:
        flag = '◼'
        redis = Redis()
        state = redis.get('state')
        if state:
            state = state.decode()
            if state == 'playing':
                flag = '▶'
            elif state == 'paused':
                flag = '‖'
    return f'{flag} {title} | {num:02d}/{tracks:02d} {album} | {artist}'


@click.command()
@click.argument('file')
def play(file):
    loop = GLib.MainLoop()
    player = Player(loop=loop)
    threading.Thread(target=player.play, args=(file,)).start()
    loop.run()


@click.command()
def spin():
    loop = GLib.MainLoop()
    scrobbler = Scrobbler()
    threading.Thread(target=scrobbler.scrobble_plays, daemon=True).start()
    reader = NFCReader()
    threading.Thread(target=reader.listen, daemon=True).start()
    player = Player(loop=loop)
    threading.Thread(target=player.spin).start()
    loop.run()


@click.command()
@click.option('--clear', is_flag=True)
@click.option('--prepend', is_flag=True)
@click.option('--remove', is_flag=True)
@click.argument('tracks', nargs=-1)
def queue(clear, prepend, remove, tracks):
    redis = Redis()
    if clear:
        clear_queue()
    if remove:
        for file in tracks:
            track = os.path.realpath(file)
            redis.lrem('queue', 0, track)
    else:
        if tracks:
            queue_files(tracks, prepend)


def show_queued_tracks(count=-1):
    redis = Redis()
    for entry in redis.lrange('queue', 0, count-1):
        track = json.loads(entry.decode())
        print(format_track_text(track, flag=' '))


@click.command()
@click.option('--repeat', default=0, show_default=True)
def show_queue(repeat):
    show_queued_tracks()
    while repeat:
        time.sleep(repeat)
        os.system('clear')
        show_queued_tracks()


def show_previous_tracks(count=-1):
    redis = Redis()
    for entry in reversed(redis.lrange('recently_played', 0, count-1)):
        track = json.loads(entry.decode())
        print(format_track_text(track, flag=' '))


@click.command()
@click.option('--repeat', default=0, show_default=True)
def show_previous(repeat):
    show_previous_tracks()
    while repeat:
        time.sleep(repeat)
        os.system('clear')
        show_previous_tracks()


def show_current_track():
    redis = Redis()
    track = redis.get('current_track')
    if track:
        print(format_track_text(json.loads(track.decode())))
    else:
        print('◼ [nothing playing]')


@click.command()
def show_playing():
    show_current_track()


@click.command()
@click.option('--repeat', default=0, show_default=True)
def show_summary(repeat):
    try:
        height = os.get_terminal_size()[1]
    except OSError:
        height = 24
    show_previous_tracks(int(height/2) - 2)
    show_current_track()
    show_queued_tracks(int(height/2))
    while repeat:
        time.sleep(repeat)
        os.system('clear')
        try:
            height = os.get_terminal_size()[1]
        except OSError:
            height = 24
        show_previous_tracks(int(height/2) - 2)
        show_current_track()
        show_queued_tracks(int(height/2))


@click.command()
def pause():
    redis = Redis()
    redis.set('command', 'pause')


def skip_current_track():
    redis = Redis()
    redis.set('command', 'skip')


@click.command()
def skip():
    skip_current_track()


@click.command()
def next_track():
    redis = Redis()
    redis.set('command', 'next')


@click.command()
def previous_track():
    redis = Redis()
    redis.set('command', 'previous')


@click.command()
def stop():
    redis = Redis()
    redis.set('command', 'stop')


@click.command()
def quit():
    redis = Redis()
    redis.set('command', 'quit')


@click.command()
@click.argument('tracks', nargs=-1)
def interrupt(tracks):
    redis = Redis()
    track = redis.getdel('current_track')
    if track:
        redis.lpush('queue', track)
    for file in reversed(tracks):
        track = os.path.realpath(file)
        tags = TinyTag.get(track)
        redis.lpush(
            'queue',
            json.dumps({'file': track, 'tags': tags.as_dict()}),
        )
    redis.set('command', 'skip')
