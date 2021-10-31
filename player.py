# Minimum install to get M4A files playing on Raspberry Pi raspbian.
#
# sudo apt-get -y install \
#     gstreamer1.0-alsa \
#     gstreamer1.0-plugins-good \
#     gstreamer1.0-plugins-bad \
#     gstreamer1.0-plugins-ugly \
#     python3-gst-1.0


pi@raspberrypi:~ $ python3
Python 3.7.3 (default, Jan 22 2021, 20:04:44) 
[GCC 8.3.0] on linux
Type "help", "copyright", "credits" or "license" for more information.

>>> import gi
>>> gi.require_version('Gst', '1.0')
>>> from gi.repository import GLib, Gst
>>> pl = Gst.ElementFactory.make('playbin', 'player')
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "/usr/lib/python3/dist-packages/gi/overrides/Gst.py", line 230, in make
    return Gst.ElementFactory.make(factory_name, instance_name)
  File "/usr/lib/python3/dist-packages/gi/overrides/Gst.py", line 589, in fake_method
    raise NotInitialized("Please call Gst.init(argv) before using GStreamer")
gi.overrides.Gst.NotInitialized: Please call Gst.init(argv) before using GStreamer

>>> Gst.init(None)
[]
>>> pl = Gst.ElementFactory.make('playbin', 'player')
>>> pl.set_state(Gst.State.NULL)
<enum GST_STATE_CHANGE_SUCCESS of type Gst.StateChangeReturn>

>>> pl.set_property('uri', 'file:///home/pi/example.m4a')
>>> pl.set_state(Gst.State.PLAYING)
<enum GST_STATE_CHANGE_ASYNC of type Gst.StateChangeReturn>
