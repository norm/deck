deck
====

A digital music player for the 20th century.


## The problem to solve

I still mostly listen to music from my own music library, for two reasons:

*   there are many albums and tracks important to me that just don't exist on
    streaming services.
*   I am far too used to choosing music to listen to using smart playlists,
    such as "my favourites that I've not listened to in over two months"

Plus, more than once I've been in the situation where my current library
(iTunes) has stopped syncing to my phone, corrupted itself, or just revamped
the UI to make it harder for me to listen to music so Apple can promote their
streaming service.


## The design

The whiteboard sketch level description is:

1.  A way of storing, categorising, and arranging music.

    * add music from local files
    * add music from CDs
    * add music from the internet
    * sync playlists to/from streaming services
    * use useful metadata from musicbrainz/last.fm/etc
    * store complete history of metadata updates (inc import from last.fm of
      historical plays)

2.  Copies of this collection living in the cloud, in my house, and in my
    pocket.

    * cloud backups of music files, a centralised copy of the database
    * a complete local copy and player running on a raspberry pi/Mac
    * iOS app player that can sync subsets of the library for offline playing


## Raspberry Pi requirements

Minimum install to get music files playing on Raspberry Pi (raspbian):

    sudo apt-get -y install \
        gstreamer1.0-alsa \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        python3-gst-1.0 \
        redis


## Usage

    sudo pip install .
    deck play track.mp3
