import time
import json
import sys
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import xbmcvfs

__addon_name__ = 'vanderwijk.iivvoo.kar'

class Log(object):
    DEBUG = 0
    INFO = 1
    NOTICE = 2
    WARNING = 3
    ERROR = 4
    SEVERE = 5
    FATAL = 6
    NONE = 7

    def log(self, msg, level=NOTICE):
        xbmc.log(msg=msg, level=level)

    def debug(self, msg):
        self.log(msg, self.DEBUG)

    def info(self, msg):
        self.log(msg, self.INFO)

    def error(self, msg):
        self.log(msg, self.ERROR)


DBURL = "http://pi.m3r.nl/db.sqlite"

"""
    Download the database, store it locally, open it as file,
    use it to provide additional navigation and searching

"""

log = Log()

# args contains the plugin id and an optional path / args. Urlparse it.

log.info("KAR startup, args: {0}".format(" ".join(sys.argv)))

import os, sys
LIB_DIR = xbmc.translatePath( os.path.join( xbmcaddon.Addon(id=__addon_name__).getAddonInfo('path'), 'resources', 'lib' ) )
sys.path.append (LIB_DIR)

DEBUG = xbmcaddon.Addon(id=__addon_name__).getSetting('debug')

import easywebdav
import requests


import urlparse, urllib
import sqlite3

class DB(object):
    def __init__(self, filename):
        log.info("Opening database {0}".format(filename))
        self.filename = filename
        self._db = sqlite3.connect(self.filename)
        self._cursor = self._db.cursor()

    def execute(self, statement, *values):
        log.info("EXEC {0} {1}".format(statement, ",".join(values)))

        res = self._cursor.execute(statement, values)
        self._db.commit()
        return res

class KVStore(DB):
    def __init__(self, filename):
        super(KVStore, self).__init__(filename)
        self.execute("""CREATE TABLE IF NOT EXISTS kvstore
                        (key TEXT PRIMARY KEY, value BLOB)""")

    def put(self, key, value):
        self.execute("""INSERT OR REPLACE INTO kvstore (key, value) VALUES (?, ?)""", key, value)

    def get(self, key):
        res = self.execute("""SELECT key, value FROM kvstore WHERE key = ?""", key)
        if res is None:
            return None
        item = res.fetchone()
        if item is None:
            return None
        return item[1]

class MediaDB(DB):
    def genres(self):
        """ fetch genres from the database """

    def search(self, type, query="", genre=None, year=None):
        """ query media databases based on certain clauses """
        if type == "movie":
            table = "movieinfo"
        else:
            table = "tvshowinfo"

        res = self.execute("""SELECT path, title
                              FROM {0}
                              WHERE lower(title) like ?""".format(table),
                           '%{0}%'.format(query.strip().lower())
                     )
        return res.fetchall()

class RecentlyPlayed(object):
    LIMIT = 20

    def __init__(self, kvstore):
        self.kvstore = kvstore

    def get(self):
        stored_raw = self.kvstore.get('recent')
        if stored_raw is None:
            return []
        log.info("Stored recent found: {0}".format(stored_raw))

        stored = json.loads(stored_raw)
        return stored

    def add(self, file):
        """ get folder, make it nice readable,
            add it to store """
        current = self.get() or []

        folder, file = file.rsplit('/', 1)

        newcurrent = [(folder, file)]

        for fol, fil in current[:self.LIMIT-1]:
            if fol != folder:
                newcurrent.append((fol, fil))

        self.kvstore.put('recent', json.dumps(newcurrent))

class MediaFile(object):
    """
        handle urls, translate it into components such as
        - filename
        - extension
        - parent folder
        - parent-parent folder
        .. etc

        Possible also provide de DAV interfacing, wrapping directories/
        files directly in MediaFile (..Folder) object?
    """

class KarException(Exception):
    pass

class SearchDialog(xbmcgui.WindowXMLDialog):
    """
        Not used for now. Building dialogs for Kodi is a complicated,
        buggy and cumbersome task:

        - everything has to be specified: sizes, positions of all controls
        - background for the dialog
        - handling of events is primitive
        - .. and sometimes it simply wont work. You'll find that a certain
          setup cannot be made to work.

        as an alternative, a primitive folder-based navigation with Dialog.input
        is used in stead
    """
    # http://kodi.wiki/view/WindowXML
    # http://kodi.wiki/view/HOW-TO:Add_a_new_window_or_dialog_via_skinning
    CONTROL_SEARCH_VIDEO = 26
    CONTROL_SEARCH_SHOWS = 27
    CONTROL_CANCEL = 28
    CONTROL_GENRELIST = 12001

    def onInit(self):
        self.s = xbmcgui.ControlList(0, 240, 1120, 160)
        self.s.setItemHeight(40)
        self.addControl(self.s)
        self.s.addItem("Hello World")
        self.s.addItem("Bye World")
        self.s.addItem("Kodi == crap")

    def onClick(self, control):
        log.info("onClick {0}".format(str(control)))

        if control == self.CONTROL_CANCEL:
            self.close()

        if control == self.CONTROL_SEARCH_VIDEO:
            self.close()

        if control == self.CONTROL_SEARCH_SHOWS:
            self.close()

        if control == self.CONTROL_GENRELIST:
            log.info("Genre selected {0}".format(str(self.s.getSelectedItem().getLabel())))


    def xonAction(self, action):
        log.info("onAction {0} {1} {2}".format(action.getId(), action.getButtonCode(), action))
        log.info(str(self.s.getSelectedItem().getLabel()))

        # ACTION_MOUSE_LEFT_CLICK
        if action.getId() == xbmcgui.ACTION_PREVIOUS_MENU:
            self.close()
        if action.getId() == xbmcgui.ACTION_PARENT_DIR:
            self.close()

    def onControl(self, control):
        log.info("onControl {0}".format(str(control)))


class Kar(object):
    METADB_EXPIRE = 3600

    def __init__(self, argv):
        try:
            self.args = dict(urlparse.parse_qsl(sys.argv[2].lstrip('?')))
        except IndexError:
            self.args = {}
        self.plugin_url = argv[0]
        self.addon_handle = int(sys.argv[1])
        self.addon = xbmcaddon.Addon()
        self.davhost = self.addon.getSetting('davhost')
        self.davport = int(self.addon.getSetting('davport'))

        log.info("Configured DAV URL " + self.davhost)
        log.info("Configured DAV port {0}".format(self.davport))


        self.pluginid = self.addon.getAddonInfo('id')

        self.addonname = self.addon.getAddonInfo('name')
        self.dav = easywebdav.connect(self.davhost, port=self.davport)

        self.data_path = os.path.join(xbmc.translatePath("special://profile/addon_data/{0}".format(self.pluginid)))

        if not xbmcvfs.exists(self.data_path):
            xbmcvfs.mkdirs(self.data_path)

        self.store = KVStore(os.path.join(self.data_path, "kar_kvstore.sqlite"))
        self.recent = RecentlyPlayed(self.store)

        mediadb_path = self.clone_db()
        self.mediadb = MediaDB(mediadb_path)

    def clone_db(self):
        dbpath = os.path.join(self.data_path, "meta.db")

        st = xbmcvfs.Stat(dbpath)
        modified = st.st_mtime()

        log.info("AGE: {0}".format(modified - time.time()))

        if modified < time.time() - self.METADB_EXPIRE or st.st_size() < 1024 * 1024:
            r = requests.get(DBURL, stream=True)
            with open(dbpath, "wb") as metadb:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk: # filter out keep-alive chunks
                        metadb.write(chunk)
                        metadb.flush()
            log.info("Meta DB copied")

        return dbpath

    def debug():
        """ invoke remote debugger """
        import rpdb2
        rpdb2.start_embedded_debugger('pw')

    def url(self, **kwargs):
        return self.plugin_url + "?" + urllib.urlencode(kwargs)

    # handle commands
    def run(self):
        if self.davhost == "example.org":
            dialog = xbmcgui.Dialog()
            dialog.ok("Please configure first",
                      "Please configure the add-on first!",
                      "You can do this through the context menu")
            return
        # need this?
        xbmcplugin.setContent(self.addon_handle, 'movies')

        command = self.args.get('command', 'main')

        log.info("COMMAND " + command + " - " + repr(self.args))
        try:
            if hasattr(self, 'cmd_' + command):
                getattr(self, 'cmd_' + command)(self.args)
            else:
                self.cmd_main(self.args)
        except KarException as e:
            dialog = xbmcgui.Dialog()
            dialog.ok("Error occurred",
                      str(e))
            return

    def cmd_main(self, args):
        li = xbmcgui.ListItem('Browse Kar', iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="browse"), listitem=li, isFolder=True)
        li = xbmcgui.ListItem('Search Kar', iconImage='icon_search.png')
        xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="search"), listitem=li, isFolder=True)
        li = xbmcgui.ListItem('Watchlist', iconImage='DefaultMusicPlaylists.png')
        xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="watchlist"), listitem=li, isFolder=True)
        li = xbmcgui.ListItem('Favorites', iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="favorites"), listitem=li, isFolder=True)
        li = xbmcgui.ListItem('Recently Watched',  iconImage='DefaultInProgressShows.png')
        xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="recent"), listitem=li, isFolder=True)
        xbmcplugin.endOfDirectory(self.addon_handle)

    def find_video_art(self, files, name):
        """ given a video 'foo.xxx', find video art 'foo.tbn' in files and
            return its url, or return default art """

        artname = name.rsplit('.', 1)[0] + '.tbn'
        for f in files:
            filename = urlparse.urlparse(f.name.rsplit('/')[-1]).path

            if filename == artname:
                return f.name

        return 'DefaultVideo.png'

    def cmd_watchlist(self, args):
        pass

    def cmd_favorites(self, args):
        pass

    def cmd_search(self, args):
        # sd = SearchDialog("search-dialog.xml", self.addon.getAddonInfo('path'), 'default', '0')
        # sd.doModal()

        options = (dict(title="Shows by String", type="show", clause="str"),
                   dict(title="Shows by Genre", type="show", clause="genre"),
                   dict(title="Shows by year", type="show", clause="year"),
                   dict(title="Movies by String", type="movie", clause="str"),
                   dict(title="Movies by Genre", type="movie", clause="genre"),
                   dict(title="Movies by year", type="movie", clause="year"))


        clause = args.get('clause')
        type = args.get('type')

        if type and clause:
            d = xbmcgui.Dialog()
            res = d.input("Enter search")
            log.info("You searched {0}".format(str(res)))

            matches = self.mediadb.search(type, res)
            # log.info("MATCH {0}".format(str(matches)))

            for match in matches:
                path = match[0]
                if path.startswith("/data/"):
                    path = path[5:]

                ## XXX Reuse the browse art magic here
                li = xbmcgui.ListItem(match[1],  iconImage='DefaultVideo.png')
                xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="browse", path=path), listitem=li, isFolder=True)
            xbmcplugin.endOfDirectory(self.addon_handle)
        else:
            for option in options:
                li = xbmcgui.ListItem(option['title'],  iconImage='DefaultVideo.png')
                xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="search", type=option['type'], clause=option['clause']), listitem=li, isFolder=True)
            xbmcplugin.endOfDirectory(self.addon_handle)

    def cmd_browse(self, args):
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE_IGNORE_THE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_FILE)
        path = args.get('path', '')
        log.info("Kar path " + path);
        try:
            files = self.dav.ls(path)
        except requests.ConnectionError as e:
            raise KarException(str(e))

        # werkt niet
        # win = xbmcgui.Window(xbmcgui.getCurrentWindowId())
        # win.setProperty('title', 'Hello World')

        ## if there aren't too many seasons (S01, s01, season01, scan for a
        ## seasonXX.tbn file and use it as folder art

        for f in files: # [:5]: # XXX restrict, for now
            url = f.name
            # only use the last path part, no slashes
            name = urlparse.urlparse(url).path.rsplit('/')[-1]
            ext = name.rsplit('.')[-1]

            readable_name = urllib.unquote(name)
            if name.startswith("."):
                continue
            if not name:
                continue # skip /

            isfolder = False

            if f.contenttype == "httpd/unix-directory":
                isfolder = True
                command = "browse"
                fanart_path = path + '/' + name + '/' + 'fanart.jpg'
                folderart_path = path + '/' + name + '/' + 'folder.jpg'
                fanart_url = "http://{0}:{1}{2}".format(self.davhost, self.davport, fanart_path)
                folderart_url = "http://{0}:{1}{2}".format(self.davhost, self.davport, folderart_path)

                li = xbmcgui.ListItem(readable_name,
                                      iconImage='DefaultFolder.png')
                li.setInfo("video", {"title": readable_name})

                ## This overrides the iconImage in ListItem. If it's not present,
                ## it means no iamge at all

                li.setArt({'thumb': folderart_url,
                           'fanart': fanart_url})
            elif ext not in ('mp4', 'avi', 'mkv'):
                continue
            else:
                command = "play"
                li = xbmcgui.ListItem(readable_name, iconImage='DefaultVideo.png')
                li.setInfo("video", { "title": readable_name, "size": f.size})
                # scan in the furrent 'files' for a .tbn equiv. If it's
                # there, use it as art
                art = self.find_video_art(files, name)
                # fanart could be series fanart in parent folder
                li.setArt({'thumb': art,
                           'fanart': art})



            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command=command, path=path + '/' + name), listitem=li, isFolder=isfolder)
        xbmcplugin.endOfDirectory(self.addon_handle)

    def cmd_play(self, args):
        # xbmcgui.Dialog().ok(self.addonname, "PLAY", args.get('path', '?'), "?")
        player = xbmc.Player()

        path = args.get('path', '')
        url = 'http://{0}:{1}{2}'.format(self.davhost, self.davport, urllib.quote(path))

        log.info("PLAY " + url)

        name = urlparse.urlparse(url).path.rsplit('/')[-1]
        readable_name = urllib.unquote(name)

        li = xbmcgui.ListItem(readable_name, iconImage='DefaultVideo.png')
        li.setInfo("video", { "Title": readable_name })

        self.recent.add(path)
        player.play(url, li)

    def cmd_recent(self, args):
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        recent = self.recent.get()
        for folder, file in recent:
            ## reuse stuff in browse!
            log.info("RECENT {0}".format(folder))
            readable_folder = urllib.unquote(folder)
            readable_file = urllib.unquote(file)
            readable_folder = " - ".join(readable_folder.lstrip('/').split("/"))

            entry = "{0} -> {1}".format(readable_folder, readable_file)
            li = xbmcgui.ListItem(entry,
                                  iconImage='DefaultFolder.png')
            li.setInfo("video", {"title": entry})
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=self.url(command="browse", path=folder), listitem=li, isFolder=True)
        xbmcplugin.endOfDirectory(self.addon_handle)


k = Kar(sys.argv)
k.run()
