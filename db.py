#!/usr/bin/env python

import sqlite3
import re
import xml.etree.ElementTree as xml

db = sqlite3.connect("db.sqlite")
cursor = db.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS movieinfo (
        path TEXT PRIMARY KEY,
        title TEXT,
        imdb TEXT,
        year INTEGER,
        plot TEXT,
        rating FLOAT,
        genre TEXT
    )""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tvshowinfo (
        path TEXT PRIMARY KEY,
        title TEXT,
        imdb TEXT,
        year INTEGER,
        plot TEXT,
        rating FLOAT,
        genre TEXT
    )""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS genres (
        genre TEXT PRIMARY KEY
    )""")
db.commit()

## We can skip episode details. They're not relevant for searching
## and can be parsed on demand - eposide folders aren't that big
## (and if it is, e.g. a dailyshow, skip it
unknown = set()
allgenres = set()

def tag_text(tree, tag):
    tag = tree.find(tag)
    if tag is not None:
        return tag.text
    return ""

def tag_text_all(tree, tag):
    tags = tree.findall(tag)
    if tags:
        return [tag.text for tag in tags if tag.text]
    return []

def get_genres(tree):
    g = []

    genres = tag_text_all(tree, "genre")
    for genre in genres:
        for splitgenre in re.split("[/,\s]+", genre):
            g.append(splitgenre.lower())
            allgenres.add(splitgenre.lower())

    return g

def handle_record(record):
    # print "new record", record[0]
    # import pdb; pdb.set_trace()

    #Alternatively, handle title: something format
    
    path = record[0]
    if path.endswith(".nfo"):
        path = path.rsplit('/', 1)[0]

    xmltxt = "".join(record[1:])
    # print xmltxt
    if not xmltxt.startswith("<?xml"):
        xmltxt = '<?xml version="1.0"?>' + xmltxt

    try:
        tree = xml.fromstring(xmltxt)
    except xml.ParseError:
        print xmltxt
        return

    if tree.tag == "movie":
        print "Movie"
        title = tag_text(tree, "title")
        plot = tag_text(tree, "plot")
        imdb = tag_text(tree, "id")
        try:
            year = int(tag_text(tree, "year"))
        except (TypeError, ValueError):
            year = 1900

        rating = tag_text(tree, "rating")
        genre = "".join("|{0}|".format(g) for g in get_genres(tree))

        ## genre can also be foo / bar (not multi tag)

        cursor.execute("""INSERT OR REPLACE INTO movieinfo (path, title, imdb, year, plot, rating, genre) VALUES (?, ?, ?, ?, ?, ?, ?)""", (path, title, imdb, year, plot, rating, genre))
        db.commit()

    elif tree.tag == "episodedetails":
        print "Episode"
    elif tree.tag == "xbmcmultiepisode":
        print "Multi Episode"
    elif tree.tag == "tvshow":
        print "TVshow"
        title = tag_text(tree, "title")
        plot = tag_text(tree, "plot")
        imdb = tag_text(tree, "id")
        try:
            year = int(tag_text(tree, "year"))
        except (TypeError, ValueError):
            year = 1900

        rating = tag_text(tree, "rating")
        genre = "".join("|{0}|".format(g) for g in get_genres(tree))

        ## genre can also be foo / bar (not multi tag)

        cursor.execute("""INSERT OR REPLACE INTO tvshowinfo (path, title, imdb, year, plot, rating, genre) VALUES (?, ?, ?, ?, ?, ?, ?)""", (path, title, imdb, year, plot, rating, genre))
        db.commit()
    else:
        print "Don't know type", tree.tag
        unknown.add(tree.tag)


record = []
with open("db.txt", "r") as source:
    for line in source:
        line = line.strip()

        if line.startswith("###"):
            if record:
                handle_record(record)
                record = []
            path = line.split(" ", 1)[-1]
            record.append(path)
        else:
            record.append(line)

if record:
    handle_record(record)

print list(allgenres)
for g in allgenres:
    if g not in ("and", "or" ):
        cursor.execute("""INSERT OR REPLACE INTO genres (genre) VALUES (?)""", (g,))

db.commit()

print unknown
db.close()
