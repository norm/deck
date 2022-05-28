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
    def __init__(self):
        self.player = Gst.ElementFactory.make('playbin', 'player')
        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)
        self.state = Gst.State.NULL

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

    def play(self, loop, track):
        self.play_track(track)
        loop.quit()

    def play_track(self, track):
        if os.path.isfile(track):
            print('-- now playing "%s"' % track)
            file = os.path.realpath(track)
            self.playing = True
            self.player.set_property('uri', 'file://' + file)
            self.player.set_state(Gst.State.PLAYING)
            while self.playing:
                time.sleep(1)
        else:
            print('** no file "%s"' % track)


@click.command()
@click.argument('file')
def play(file):
    mainclass = Player()
    loop = GLib.MainLoop()
    _thread.start_new_thread(mainclass.play, (loop, file))
    loop.run()
