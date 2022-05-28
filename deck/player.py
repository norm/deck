import gi
gi.require_version('Gst', '1.0')

from gi.repository import GLib, GObject, Gst
Gst.init(None)

import click
import os
import sys
import _thread
import time


class Player:
    def __init__(self, loop):
        self.player = Gst.ElementFactory.make('playbin', 'player')
        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)
        self.state = Gst.State.NULL
        self.loop = loop

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.STATE_CHANGED:
            state = message.parse_state_changed()[1]
            if state != self.state:
                self.state = state
        elif message.type == Gst.MessageType.EOS:
            self.player.set_state(Gst.State.NULL)
            self.playing = False
        elif message.type == Gst.MessageType.ERROR:
            self.player.set_state(Gst.State.NULL)
            err, debug = message.parse_error()
            print('** error:', err, debug)
            self.playing = False
        elif message.type in [
            Gst.MessageType.ASYNC_DONE,
            Gst.MessageType.DURATION_CHANGED,
            Gst.MessageType.LATENCY,
            Gst.MessageType.NEW_CLOCK,
            Gst.MessageType.STREAM_START,
            Gst.MessageType.STREAM_STATUS,
            Gst.MessageType.TAG,
        ]:
            pass
        else:
            print("** unknown message type", message.type)

    def play(self, track):
        self.play_track(track)
        self.quit()

    def play_track(self, track):
        if os.path.isfile(track):
            print('-- now playing "%s"' % track)
            file = os.path.realpath(track)
            self.playing = True
            self.player.set_property('uri', 'file://' + file)
            self.player.set_state(Gst.State.PLAYING)
            while self.playing:
                time.sleep(1)
                self.output_player_state()
        else:
            print('** no file "%s"' % track)

    def output_player_state(self):
        # FIXME a terminal wider than 80 chars
        progress_bar_width = 60

        # FIXME a track over an hour long
        duration = self.player.query_duration(Gst.Format.TIME)[1]
        position = self.player.query_position(Gst.Format.TIME)[1]
        if duration < 0 or position < 0:
            # unintialised state, don't report
            return

        progress = int((position / duration) * progress_bar_width)
        progress_bar = ('_' * (progress-1)) + '|'

        # 12345678901234567890123456789012345678901234567890123456789012345678901234567890
        #   ▶  00:07 [__________|________________________________________________] 00:31
        print(
            "  ▶  %s [%s] %s" % (
                self.minutes_seconds(position),
                progress_bar.ljust(progress_bar_width, '_'),
                self.minutes_seconds(duration),
            ),
            end='\r',
            flush=True,
        )

    def minutes_seconds(self, t):
        s,ns = divmod(t, 1000000000)
        m,s = divmod(s, 60)
        if m < 60:
            return "%02i:%02i" %(m,s)
        else:
            h,m = divmod(m, 60)
            return "%i:%02i:%02i" %(h,m,s)

    def quit(self):
        self.loop.quit()

@click.command()
@click.argument('file')
def play(file):
    loop = GLib.MainLoop()
    mainclass = Player(loop=loop)
    _thread.start_new_thread(mainclass.play, (file,))
    loop.run()
