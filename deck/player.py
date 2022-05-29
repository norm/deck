import gi
gi.require_version('Gst', '1.0')

from gi.repository import GLib, GObject, Gst
Gst.init(None)

import click
import itertools
import os
from select import select
import sys
import termios
import _thread
import time
import tty
from deck.redis import Redis


class Player:
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
            print('** error:', err, debug, end='\r\n')
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
            print("** unknown message type", message.type, end='\r\n')

    def play(self, track):
        self.play_track(track)
        self.quit()

    # FIXME store played tracks (FIFO queue) in redis
    def spin(self):
        print('[Space]:pause/play  [L]:skip fwd    [J]:skip back  [1234567890]:position', end='\r\n')
        print('[N]:next track      [P]:prev track  [S]:stop       [^C]:quit', end='\r\n')
        print('[Q/+]:vol up        [A/-]:vol down  [M]:mute', end='\r\n\n')
        while True:
            if self.state == 'stopped':
                char = self.wait_for_key(timeout=0.2)
                if char and ord(char) == 32:
                    self.player_state(Gst.State.NULL)
            else:
                track = self.redis.lindex('queue', 0)
                if track:
                    self.play_track(track.decode())
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
        if os.path.isfile(track):
            self.output_text_state('-- now playing "%s"' % track)
            file = os.path.realpath(track)
            self.player.set_property('uri', 'file://' + file)
            self.player_state(Gst.State.PLAYING)
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
                    elif char in ['n', 'N']:
                        self.next_track()
                    elif char in ['p', 'P']:
                        self.previous_track()
                    elif ord(char) in range(48, 58):
                        self.set_position(char)
                self.check_for_command()
                self.output_player_state()
        else:
            self.output_text_state('** no file "%s"' % track)
        if self.state not in ['stopped', 'previous']:
            self.redis.lpop('queue')
            self.redis.lpush('recently_played', track)
            self.redis.ltrim('recently_played', 0, 99)

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
            else:
                print('\r\n** unknown command received:', command, end='\r\n')

    def pause_or_resume(self):
        if self.state in [Gst.State.PLAYING, 'seek_forwards', 'seek_backwards']:
            self.player_state(Gst.State.PAUSED)
            self.relative_seek(-0.05, show_state=False)
        elif self.state in [Gst.State.PAUSED, 'stopped']:
            self.player_state(Gst.State.PLAYING)
        time.sleep(0.1)

    def stop(self):
        self.player.set_state(Gst.State.NULL)
        self.state = 'stopped'
        self.playing = False

    def next_track(self):
        self.player_state(Gst.State.PAUSED)
        self.player_state(Gst.State.NULL)
        self.playing = False

    def previous_track(self):
        track = self.redis.lpop('recently_played')
        self.redis.lpush('queue', track)
        self.player_state(Gst.State.PAUSED)
        self.player.set_state(Gst.State.NULL)
        self.state = 'previous'
        self.playing = False

    def player_state(self, state):
        self.player.set_state(state)
        self.state = state

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
        # FIXME a terminal wider than 80 chars
        progress_bar_width = 44

        # FIXME a track over an hour long
        duration = self.player.query_duration(Gst.Format.TIME)[1]
        position = self.player.query_position(Gst.Format.TIME)[1]
        if duration < 0 or position < 0:
            # unintialised state, no times
            duration_time = '--:--'
            position_time = '--:--'
            progress_bar = '_' * progress_bar_width
        else:
            progress = int((position / duration) * progress_bar_width)
            progress_bar = (('_' * (progress-1)) + '|').ljust(progress_bar_width, '_')
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
        elif self.state == Gst.State.NULL:
            state = next(self.spinner)
        else:
            state = '?'

        # 12345678901234567890123456789012345678901234567890123456789012345678901234567890
        #   ▶  [==========]   00:04 [______|_____________________________________] 00:31
        print(
            "  %s  [%s]   %s [%s] %s" % (
                state,
                volume_bar,
                position_time,
                progress_bar,
                duration_time,
            ),
            end='\r',
            flush=True,
        )

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

    def minutes_seconds(self, t):
        s,ns = divmod(t, 1000000000)
        m,s = divmod(s, 60)
        if m < 60:
            return "%02i:%02i" %(m,s)
        else:
            h,m = divmod(m, 60)
            return "%i:%02i:%02i" %(h,m,s)

    def quit(self):
        termios.tcsetattr(
            sys.stdin.fileno(),
            termios.TCSANOW,
            self.original_terminal_state,
        )
        print()
        self.loop.quit()


@click.command()
@click.argument('file')
def play(file):
    loop = GLib.MainLoop()
    mainclass = Player(loop=loop)
    _thread.start_new_thread(mainclass.play, (file,))
    loop.run()

@click.command()
def spin():
    loop = GLib.MainLoop()
    mainclass = Player(loop=loop)
    _thread.start_new_thread(mainclass.spin, ())
    loop.run()


@click.command()
@click.option('--clear', is_flag=True)
@click.argument('tracks', nargs=-1)
def queue(clear, tracks):
    redis = Redis()
    if clear:
        redis.ltrim('queue', 1, 0)
    else:
        for file in tracks:
            redis.rpush('queue', os.path.realpath(file))


@click.command()
@click.option('--repeat', default=0, show_default=True)
def show_queue(repeat):
    redis = Redis()
    for track in redis.lrange('queue', 0, -1):
        print(track.decode())
    while repeat:
        time.sleep(repeat)
        os.system('clear')
        for track in redis.lrange('queue', 0, -1):
            print(track.decode())


@click.command()
@click.option('--repeat', default=0, show_default=True)
def show_previous(repeat):
    redis = Redis()
    for track in redis.lrange('recently_played', 0, -1):
        print(track.decode())
    while repeat:
        time.sleep(repeat)
        os.system('clear')
        for track in redis.lrange('recently_played', 0, -1):
            print(track.decode())


@click.command()
def pause():
    redis = Redis()
    redis.set('command', 'pause')


@click.command()
def next_track():
    redis = Redis()
    redis.set('command', 'next')


@click.command()
def previous_track():
    redis = Redis()
    redis.set('command', 'previous')
