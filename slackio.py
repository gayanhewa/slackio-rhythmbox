# __init__.py
#
# Copyright (C) 2010 - Filipp Ivanov
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# The Rhythmbox authors hereby grant permission for non-GPL compatible
# GStreamer plugins to be used and distributed together with GStreamer
# and Rhythmbox. This permission is above and beyond the permissions granted
# by the GPL license by which Rhythmbox is covered. If you modify this code
# you may extend this exception to your version of the code, but you are not
# obligated to do so. If you do not wish to do so, delete this exception
# statement from your version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.

import rb
import gi
from gi.repository import Gio, GLib, GObject, Peas
from gi.repository import RB
import pycurl
try:
    # python 3
    from urllib.parse import urlencode
except ImportError:
    # python 2
    from urllib import urlencode
import gettext
gettext.install('rhythmbox', RB.locale_dir())

NORMAL_SONG_ARTIST = 'artist'
NORMAL_SONG_TITLE  = 'title'
NORMAL_SONG_ALBUM  = 'album'
STREAM_SONG_ARTIST = 'rb:stream-song-artist'
STREAM_SONG_TITLE  = 'rb:stream-song-title'
STREAM_SONG_ALBUM  = 'rb:stream-song-album'

PROPERTIES_IFACE_NAME = 'org.freedesktop.DBus.Properties'

class SlackIoPlugin (GObject.Object, Peas.Activatable):
    __gtype_name__ = 'SlackIoPlugin'
    object = GObject.property(type=GObject.Object)

    def __init__ (self):
        GObject.Object.__init__ (self)

    def _init_dbus_proxies(self):
        self.proxies = {}
        bus_type = Gio.BusType.SESSION
        flags = 0
        iface_info = None

    def do_activate (self):
        shell = self.object
        sp = shell.props.shell_player
        self.psc_id  = sp.connect ('playing-song-changed',
                                   self.playing_entry_changed)
        self.pc_id   = sp.connect ('playing-changed',
                                   self.playing_changed)
        self.pspc_id = sp.connect ('playing-song-property-changed',
                                   self.playing_song_property_changed)

        self.current_entry = None
        self.current_artist = None
        self.current_title = None
        self.current_album = None

        self._init_dbus_proxies ()

        if sp.get_playing ():
          self.set_entry (sp.get_playing_entry ())

    def do_deactivate (self):
        shell = self.object
        sp = shell.props.shell_player
        sp.disconnect (self.psc_id)
        sp.disconnect (self.pc_id)
        sp.disconnect (self.pspc_id)

        if self.current_entry is not None:
          self.restore_status ()

    def playing_changed (self, sp, playing):
        if playing:
          self.set_entry (sp.get_playing_entry ())
        else:
          self.current_entry = None
          self.restore_status ()

    def playing_entry_changed (self, sp, entry):
        if sp.get_playing ():
          self.set_entry (entry)

    def playing_song_property_changed (self, sp, uri, property, old, new):
        relevant = False
        if sp.get_playing () and property in (NORMAL_SONG_ARTIST, STREAM_SONG_ARTIST):
          self.current_artist = new
          relevant = True
        elif sp.get_playing () and property in (NORMAL_SONG_TITLE, STREAM_SONG_TITLE):
          self.current_title = new
          relevant = True
        elif sp.get_playing () and property in (NORMAL_SONG_ALBUM, STREAM_SONG_ALBUM):
          self.current_album = new
          relevant = True

    def set_entry (self, entry):
        if rb.entry_equal(entry, self.current_entry):
          return
        self.current_entry = entry
        self.set_status_from_entry ()

    def set_status_from_entry (self):
        shell = self.object
        db = shell.get_property ("db")
        self.current_artist = self.current_entry.get_string(RB.RhythmDBPropType.ARTIST)
        self.current_title = self.current_entry.get_string(RB.RhythmDBPropType.TITLE)
        self.current_album = self.current_entry.get_string(RB.RhythmDBPropType.ALBUM)

        if self.current_entry.get_entry_type().props.category == RB.RhythmDBEntryCategory.STREAM:
          if not self.current_artist:
            self.current_artist = db.entry_request_extra_metadata (self.current_entry, STREAM_SONG_ARTIST)
          if not self.current_title:
            self.current_title  = db.entry_request_extra_metadata (self.current_entry, STREAM_SONG_TITLE)
          if not self.current_album:
            self.current_album  = db.entry_request_extra_metadata (self.current_entry, STREAM_SONG_ALBUM)

        self.set_status ()

    def set_status (self):
        subs = {
            'artist': self.current_artist,
            'album': self.current_album,
            'title': self.current_title
        }
        if self.current_artist:
          if self.current_title:
            # Translators: do not translate %(artist)s or %(title)s, they are
            # string substitution markers (like %s) for the artist and title of
            # the current playing song.  They can be reordered if necessary.
            new_status = _(u"♫ %(artist)s - %(title)s ♫") % subs
          elif self.current_album:
            # Translators: do not translate %(artist)s or %(album)s, they are
            # string substitution markers (like %s) for the artist and album name
            # of the current playing song.  They can be reordered if necessary.
            new_status = _(u"♫ %(artist)s - %(album)s ♫") % subs
        elif self.current_album:
          # Translators: do not translate %(album)s, it is a string substitution
          # marker (like %s) for the album name of the current playing song.
          new_status = _(u"♫ %(album)s ♫") % subs
        elif self.current_title:
          # Translators: do not translate %(title)s, it is a string substitution
          # marker (like %s) for the title of the current playing song.
          new_status = _(u"♫ %(title)s ♫") % subs
        else:
          new_status = _(u"♫ Listening to music... ♫")
        self.post_update(new_status)

    def post_update (self, new_status):
        c = pycurl.Curl()
        c.setopt(c.URL, '')
        status = '{ "text": "'+new_status+'" }'
        post_data = {'payload': status}
        postfields = urlencode(post_data)
        c.setopt(c.POSTFIELDS, postfields)
        c.perform()
        c.close()